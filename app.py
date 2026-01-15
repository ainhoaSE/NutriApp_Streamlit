import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import math
from datetime import datetime
import google.generativeai as genai

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NutriApp AI", layout="wide", page_icon="🥗")

# --- CSS ---
def inject_custom_css():
    st.markdown("""
        <style>
        .stTextArea textarea { height: 60vh !important; font-size: 16px !important; }
        </style>
        """, unsafe_allow_html=True)

# --- BASE DE DATOS (NUEVA TABLA PROGRESS) ---
def init_db():
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS profiles
                 (username TEXT PRIMARY KEY, edad INTEGER, peso REAL, altura INTEGER, 
                  sexo TEXT, actividad TEXT, objetivo TEXT, 
                  prot_g_kg REAL, grasa_g_kg REAL, carbos_pct REAL)''')
    
    # NUEVA TABLA PROGRESO: Ahora guarda medidas
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (username TEXT, fecha TEXT, peso REAL, cintura REAL, cuello REAL, cadera REAL, grasa_pct REAL)''')
                 
    c.execute('''CREATE TABLE IF NOT EXISTS diets (id INTEGER PRIMARY KEY, username TEXT, fecha TEXT, contenido TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY, username TEXT, titulo TEXT, contenido TEXT, categoria TEXT)''')
    conn.commit()
    conn.close()

def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    c.execute(query, params)
    if fetch: data = c.fetchall()
    else: data = None; conn.commit()
    conn.close()
    return data

# --- CÁLCULOS NUTRICIONALES Y CORPORALES ---
def calcular_bmr_tdee(peso, altura, edad, sexo, actividad):
    if sexo == "Hombre": bmr = (10 * peso) + (6.25 * altura) - (5 * edad) + 5
    else: bmr = (10 * peso) + (6.25 * altura) - (5 * edad) - 161
    factores = {"Sedentario (Poco o nada)":1.0, "Ligero (1-3 días/sem)":1.2, "Moderado (4-5 días/sem)":1.375, "Activo (5-6 días/sem)":1.55, "Muy Activo (7 o más)":1.725}
    return bmr, bmr * factores.get(actividad, 1.2)

def calcular_calorias_objetivo(tdee, objetivo):
    delta = 0
    if "Déficit Leve" in objetivo: delta = -250
    elif "Déficit Moderado" in objetivo: delta = -400
    elif "Superávit Leve" in objetivo: delta = 150
    elif "Superávit Moderado" in objetivo: delta = 300
    return tdee + delta, delta

# FÓRMULA DE LA MARINA DE EE.UU. PARA GRASA CORPORAL
def calcular_grasa_corporal(sexo, cintura_cm, cuello_cm, cadera_cm, altura_cm):
    try:
        if sexo == "Hombre":
            # Fórmula Hombres
            return 495 / (1.0324 - 0.19077 * math.log10(cintura_cm - cuello_cm) + 0.15456 * math.log10(altura_cm)) - 450
        else:
            # Fórmula Mujeres (Incluye cadera)
            return 495 / (1.29579 - 0.35004 * math.log10(cintura_cm + cadera_cm - cuello_cm) + 0.22100 * math.log10(altura_cm)) - 450
    except:
        return 0.0 # Si hay error matemático (ej: medidas imposibles)

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# --- IA GENERADORES ---
def generar_receta_individual_ia(ingredientes, categoria, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        return model.generate_content(f"Chef. Receta {categoria} con {ingredientes}. Título, Ingredientes, Pasos, Macros.").text
    except Exception as e: return f"Error: {str(e)}"

def generar_dieta_inteligente(perfil, recetas_raw, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        nombres_recetas = [r[0] for r in recetas_raw] if recetas_raw else []
        lista_existente = ", ".join(nombres_recetas) if nombres_recetas else "Ninguna."

        prompt = f"""
        Actúa como Nutricionista Personal.
        
        META CALÓRICA DIARIA: {perfil['calorias_objetivo']:.0f} kcal
        
        TUS HERRAMIENTAS:
        - Recetas que el usuario YA TIENE y deberías reusar: {lista_existente}
        
        ---------------------------------------------------------
        TAREA 1: EL PLAN SEMANAL
        Genera el plan siguiendo ESTRICTAMENTE este formato para cada día.
        NO uses tablas.
        
        FORMATO OBLIGATORIO POR DÍA (Respeta los saltos de línea):
        
        **[Día de la semana]**
        * 🍳 **Desayuno:** [Nombre del plato exacto] ([kcal] kcal)
        * 🍎 **Snack 1:** [Nombre del plato exacto] ([kcal] kcal)
        * 🥗 **Almuerzo:** [Nombre del plato exacto] ([kcal] kcal)
        * 🥛 **Snack 2:** [Nombre del plato exacto] ([kcal] kcal)
        * 🐟 **Cena:** [Nombre del plato exacto] ([kcal] kcal)
        
        **🔥 Total Día: [Suma Total] kcal**
        ---
        
        (Asegúrate de dejar una línea vacía antes del Total Día).

        ---------------------------------------------------------
        TAREA 2: GENERACIÓN DE RECETAS NUEVAS
        Si inventas platos que NO están en la lista del usuario:
        1. Escribe la receta completa al final.
        2. Usa títulos genéricos.
        3. Formato oculto para el sistema:
        
        ###NUEVAS_RECETAS###
        TITULO: [Nombre]
        CATEGORIA: [Desayuno/Almuerzo/Cena/Snack 1/Snack 2]
        CONTENIDO:
        [Receta + Macros/Calorías al final]
        END_RECIPE
        """
        resp = model.generate_content(prompt).text
        if "###NUEVAS_RECETAS###" in resp:
            parts = resp.split("###NUEVAS_RECETAS###")
            dieta, raw = parts[0].strip(), parts[1].strip()
            new_r = []
            for b in raw.split("END_RECIPE"):
                if "TITULO:" in b:
                    try:
                        lines = b.strip().split('\n')
                        t = next(l for l in lines if "TITULO:" in l).replace("TITULO:", "").strip()
                        c = next(l for l in lines if "CATEGORIA:" in l).replace("CATEGORIA:", "").strip()
                        cont = b[b.find("CONTENIDO:")+10:].strip()
                        if "Snack" in c and "1" not in c: c = "Snack 1"
                        if c not in ["Desayuno", "Almuerzo", "Cena", "Snack 1", "Snack 2"]: c = "Otros"
                        new_r.append({"titulo":t, "categoria":c, "contenido":cont})
                    except: continue
            return dieta, new_r
        return resp, []
    except Exception as e: return f"Error: {str(e)}", []

# --- IA ANALISTA (CON MEDIDAS) ---
def analizar_progreso_ia(historial_df, objetivo, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        data_txt = historial_df.to_string(index=False)
        prompt = f"""
        Actúa como Entrenador Personal experto en biometría.
        OBJETIVO: {objetivo}
        DATOS (Peso, Cintura, %Grasa):
        {data_txt}
        
        Analiza si el usuario está perdiendo grasa real o solo peso (agua/músculo).
        Fíjate mucho en la CINTURA y el %GRASA.
        Da 3 conclusiones motivadoras.
        """
        return model.generate_content(prompt).text
    except Exception as e: return f"Error: {str(e)}"

# --- INTERFAZ ---
def main():
    init_db()
    inject_custom_css()
    st.title("🥗 NutriApp AI v10.0")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    if st.session_state['logged_in']:
        menu = ["Mi Dieta Semanal", "Mis Recetas", "Mi Progreso", "Mi Perfil", "Cerrar Sesión"]
        st.sidebar.success(f"Hola, {st.session_state['username']}!")
    else:
        menu = ["Login", "Registro"]
    
    choice = st.sidebar.selectbox("Navegación", menu)

    # --- LOGIN / REGISTRO ---
    if choice == "Registro":
        st.subheader("Nuevo Usuario")
        new_user = st.text_input("Usuario")
        new_pass = st.text_input("Contraseña", type='password')
        if st.button("Crear Cuenta"):
            try: run_query("INSERT INTO users VALUES(?,?)", (new_user, make_hashes(new_pass))); st.success("Creado.")
            except: st.warning("Existe.")
    elif choice == "Login":
        st.subheader("Acceso")
        user = st.text_input("Usuario")
        passwd = st.text_input("Contraseña", type='password')
        if st.button("Entrar"):
            if run_query("SELECT * FROM users WHERE username=? AND password=?", (user, make_hashes(passwd)), fetch=True):
                st.session_state['logged_in'] = True; st.session_state['username'] = user; st.rerun()
            else: st.warning("Error.")

    # --- PERFIL ---
    elif choice == "Mi Perfil":
        st.header("👤 Configuración")
        datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_prot, d_grasa = 30, 70.0, 175, "Hombre", "Moderado (4-5 días/sem)", "Mantenimiento", 0.0, 0.0
        if datos:
            if len(datos[0]) == 10: _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_prot, d_grasa, _ = datos[0]
            else: _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj = datos[0][:7]

        with st.form("perfil_form"):
            c1, c2, c3, c4 = st.columns(4)
            edad = c1.number_input("Edad", value=d_edad)
            sexo = c2.selectbox("Sexo", ["Hombre", "Mujer"], index=0 if d_sexo=="Hombre" else 1)
            peso = c3.number_input("Peso", value=d_peso)
            altura = c4.number_input("Altura (cm)", value=d_altura)
            act_opts = ["Sedentario (Poco o nada)", "Ligero (1-3 días/sem)", "Moderado (4-5 días/sem)", "Activo (5-6 días/sem)", "Muy Activo (7 o más)"]
            try: act_idx = act_opts.index(d_act)
            except: act_idx = 0
            actividad = st.selectbox("Actividad", act_opts, index=act_idx)
            obj_opts = ["Déficit Leve (-250 kcal)", "Déficit Moderado (-400 kcal)", "Mantenimiento", "Superávit Leve (+150 kcal)", "Superávit Moderado (+300 kcal)"]
            try: obj_idx = obj_opts.index(d_obj)
            except: obj_idx = 2
            objetivo = st.selectbox("Objetivo", obj_opts, index=obj_idx)
            bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, actividad)
            cal_objetivo, delta_cal = calcular_calorias_objetivo(tdee, objetivo)
            c_info1, c_info2, c_info3 = st.columns(3)
            c_info1.metric("BMR", f"{int(bmr)}")
            c_info2.metric("TDEE", f"{int(tdee)}")
            c_info3.metric("🔥 Meta", f"{int(cal_objetivo)}", delta=f"{delta_cal}")
            cm1, cm2 = st.columns(2)
            prot_input = cm1.number_input("Prot g/kg", value=d_prot)
            grasa_input = cm2.number_input("Grasa g/kg", value=d_grasa)
            if st.form_submit_button("💾 Guardar"):
                run_query("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)", (st.session_state['username'], edad, peso, altura, sexo, actividad, objetivo, prot_input, grasa_input, 0.0))
                st.rerun()

# --- MI DIETA SEMANAL ---
    elif choice == "Mi Dieta Semanal":
        st.header("📅 Mi Dieta Semanal")
        last = run_query("SELECT contenido, fecha, id FROM diets WHERE username=? ORDER BY id DESC LIMIT 1", (st.session_state['username'],), fetch=True)
        if last:
            if st.toggle("✏️ Editar Plan"):
                txt = st.text_area("Editor", last[0][0])
                if st.button("Guardar Cambios"):
                    run_query("UPDATE diets SET contenido=? WHERE id=?", (txt, last[0][2])); st.success("Guardado"); st.rerun()
            else:
                st.caption(f"📅 Generado el: {last[0][1]}")
                st.markdown(last[0][0])
        else: st.info("No tienes dieta activa. Crea una abajo 👇")

        with st.expander("✨ Generar NUEVO Plan (Con IA)"):
            datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
            recetas_raw = run_query("SELECT titulo, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
            
            if not datos or len(datos[0]) < 10:
                st.error("Rellena tu perfil primero.")
            else:
                try: api_key = st.secrets["GOOGLE_API_KEY"]
                except: st.error("Falta API Key"); st.stop()
                _, edad, peso, altura, sexo, act, obj, prot, grasa, _ = datos[0]
                bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, act)
                cal_obj, _ = calcular_calorias_objetivo(tdee, obj)

                if st.button("Generar Plan Semanal"):
                    perf = {"calorias_objetivo": cal_obj, "objetivo": obj}
                    dieta_texto, recetas_nuevas = generar_dieta_inteligente(perf, recetas_raw, api_key)
                    st.session_state['temp_dieta'] = dieta_texto
                    st.session_state['temp_nuevas_recetas'] = recetas_nuevas

                if 'temp_dieta' in st.session_state:
                    st.markdown("### 📝 Propuesta")
                    st.markdown(st.session_state['temp_dieta'])
                    
                    nuevas = st.session_state.get('temp_nuevas_recetas', [])
                    if nuevas:
                        st.info(f"💡 Se añadirán {len(nuevas)} recetas nuevas a tu libro: " + ", ".join([r['titulo'] for r in nuevas]))

                    if st.button("✅ Confirmar y Guardar"):
                        run_query("INSERT INTO diets(username, fecha, contenido) VALUES(?,?,?)", 
                                  (st.session_state['username'], datetime.now().strftime("%Y-%m-%d %H:%M"), st.session_state['temp_dieta']))
                        
                        count = 0
                        for r in nuevas:
                            run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", 
                                      (st.session_state['username'], r['titulo'], r['contenido'], r['categoria']))
                            count += 1
                        
                        del st.session_state['temp_dieta']
                        if 'temp_nuevas_recetas' in st.session_state: del st.session_state['temp_nuevas_recetas']
                        st.success("¡Plan activado!"); st.rerun()

    # --- MIS RECETAS ---
    elif choice == "Mis Recetas":
        st.header("🍳 Mis Recetas")
        categorias = ["Desayuno", "Snack 1", "Almuerzo", "Snack 2", "Cena", "Otros"]
        tab_ver, tab_add = st.tabs(["📂 Ver y Editar", "➕ Añadir Nueva"])
        
        with tab_ver:
            tabs_cats = st.tabs(categorias)
            all_recs = run_query("SELECT titulo, contenido, id, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
            recetas_dict = {c: [] for c in categorias}
            if all_recs:
                for r in all_recs:
                    cat_db = r[3] if r[3] in categorias else "Otros"
                    recetas_dict[cat_db].append(r)

            for i, cat in enumerate(categorias):
                with tabs_cats[i]:
                    if recetas_dict[cat]:
                        for r in recetas_dict[cat]:
                            with st.expander(f"🍽️ {r[0]}"):
                                new_title = st.text_input("Título", r[0], key=f"t{r[2]}")
                                new_content = st.text_area("Contenido", r[1], key=f"r{r[2]}")
                                c1, c2 = st.columns([1,4])
                                if c1.button("Guardar", key=f"s{r[2]}"): 
                                    run_query("UPDATE recipes SET titulo=?, contenido=? WHERE id=?", (new_title, new_content, r[2]))
                                    st.success("Actualizado"); st.rerun()
                                if c2.button("Borrar", key=f"d{r[2]}"): 
                                    run_query("DELETE FROM recipes WHERE id=?", (r[2],)); st.rerun()
                    else: st.info("Vacío.")

        with tab_add:
            st.subheader("Nueva Receta")
            cat_sel = st.selectbox("Categoría", categorias)
            with st.container(border=True):
                idea = st.text_input("Ingredientes/Idea:", key="idea")
                if st.button("Generar con IA"):
                    try: api_key = st.secrets["GOOGLE_API_KEY"]
                    except: st.error("Falta API Key"); st.stop()
                    st.session_state['temp_rec'] = generar_receta_individual_ia(idea, cat_sel, api_key)
                    st.session_state['temp_tit'] = idea.split(".")[0]
            
            tf = st.text_input("Título", value=st.session_state.get('temp_tit', ''))
            cf = st.text_area("Contenido", value=st.session_state.get('temp_rec', ''))
            if st.button("Guardar Receta"):
                run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", (st.session_state['username'], tf, cf, cat_sel))
                del st.session_state['temp_rec']; st.rerun()

    # --- MI PROGRESO (AVANZADO - BIO) ---
    elif choice == "Mi Progreso":
        st.header("📉 Seguimiento Corporal Completo")
        
        # 1. Recuperar datos y perfil
        data = run_query("SELECT fecha, peso, cintura, cuello, cadera, grasa_pct FROM progress WHERE username=? ORDER BY fecha DESC", (st.session_state['username'],), fetch=True)
        perfil = run_query("SELECT peso, altura, objetivo, sexo FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        
        # 2. KPIs de Alto Nivel
        if data and perfil:
            p_actual = data[0][1]
            grasa_actual = data[0][5] if data[0][5] else 0
            cintura_actual = data[0][2] if data[0][2] else 0
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Peso", f"{p_actual} kg", delta=f"{p_actual - data[1][1]:.1f}" if len(data)>1 else None, delta_color="inverse")
            k2.metric("% Grasa (Estimado)", f"{grasa_actual:.1f} %", delta=f"{grasa_actual - data[1][5]:.1f}%" if len(data)>1 and data[1][5] else None, delta_color="inverse")
            k3.metric("Cintura", f"{cintura_actual} cm", delta=f"{cintura_actual - data[1][2]:.1f}" if len(data)>1 and data[1][2] else None, delta_color="inverse")
            
            altura_m = perfil[0][1] / 100
            k4.metric("IMC", f"{p_actual/(altura_m**2):.1f}")

        st.divider()

        # 3. Formulario de Check-in (Ahora pide medidas)
        col_form, col_graph = st.columns([1, 2])
        
        with col_form:
            st.subheader("📝 Nuevo Check-in")
            with st.form("bio_checkin"):
                f_fecha = st.date_input("Fecha", datetime.today())
                f_peso = st.number_input("Peso (kg)", step=0.1, format="%.1f")
                
                st.markdown("**Medidas (cm)** (Para calcular grasa)")
                f_cintura = st.number_input("Cintura (Ombligo)", step=0.5)
                f_cuello = st.number_input("Cuello", step=0.5)
                
                f_cadera = 0.0
                if perfil and perfil[0][3] == "Mujer":
                    f_cadera = st.number_input("Cadera (Parte ancha)", step=0.5)
                
                if st.form_submit_button("Guardar Registro"):
                    if perfil:
                        # Calcular Grasa automáticamente
                        g_pct = calcular_grasa_corporal(perfil[0][3], f_cintura, f_cuello, f_cadera, perfil[0][1])
                        
                        run_query("INSERT INTO progress VALUES (?,?,?,?,?,?,?)", 
                                  (st.session_state['username'], f_fecha.strftime("%Y-%m-%d"), f_peso, f_cintura, f_cuello, f_cadera, g_pct))
                        
                        # Actualizar peso actual en perfil
                        run_query("UPDATE profiles SET peso=? WHERE username=?", (f_peso, st.session_state['username']))
                        st.success(f"Guardado. Grasa estimada: {g_pct:.1f}%"); st.rerun()
                    else:
                        st.error("Configura tu perfil primero (Altura/Sexo necesarios)")

        with col_graph:
            if data:
                df = pd.DataFrame(data, columns=['Fecha', 'Peso', 'Cintura', 'Cuello', 'Cadera', '% Grasa'])
                df['Fecha'] = pd.to_datetime(df['Fecha'])
                
                tab_g1, tab_g2, tab_g3 = st.tabs(["📉 Peso", "🥩 % Grasa", "📏 Cintura"])
                with tab_g1: st.line_chart(df.set_index('Fecha')['Peso'])
                with tab_g2: st.line_chart(df.set_index('Fecha')['% Grasa'])
                with tab_g3: st.line_chart(df.set_index('Fecha')['Cintura'])
                
                with st.expander("Ver Tabla de Datos"):
                    st.dataframe(df.sort_values(by="Fecha", ascending=False), use_container_width=True)
                    if st.button("Borrar último registro"):
                        run_query("DELETE FROM progress WHERE username=? AND fecha=?", (st.session_state['username'], data[0][0]))
                        st.rerun()

        # 4. COACH IA
        st.subheader("🧠 Análisis Biométrico")
        if data and len(data) > 1:
            if st.button("Pedir feedback al Coach"):
                try: api = st.secrets["GOOGLE_API_KEY"]
                except: st.error("Falta API"); st.stop()
                obj_user = perfil[0][2] if perfil else "General"
                # Enviamos DataFrame con todas las medidas
                df_analisis = pd.DataFrame(data, columns=['Fecha', 'Kg', 'Cintura', 'Cuello', 'Cadera', 'Grasa_Pct'])
                st.info(analizar_progreso_ia(df_analisis, obj_user, api))

    elif choice == "Cerrar Sesión":
        st.session_state['logged_in'] = False; st.rerun()

if __name__ == '__main__':
    main()