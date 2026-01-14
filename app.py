import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from datetime import datetime
import google.generativeai as genai

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NutriApp AI", layout="wide", page_icon="🥗")

# --- BASE DE DATOS (NUEVA ESTRUCTURA V4) ---
def init_db():
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT)''')
    
    # TABLA PERFILES ACTUALIZADA con campos de macros
    # Orden: username, edad, peso, altura, sexo, actividad, objetivo, prot_g_kg, grasa_g_kg, carbos_pct
    c.execute('''CREATE TABLE IF NOT EXISTS profiles
                 (username TEXT PRIMARY KEY, edad INTEGER, peso REAL, altura INTEGER, 
                  sexo TEXT, actividad TEXT, objetivo TEXT, 
                  prot_g_kg REAL, grasa_g_kg REAL, carbos_pct REAL)''')
                  
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (username TEXT, fecha TEXT, peso REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS diets
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, contenido TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS recipes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, titulo TEXT, contenido TEXT)''')
    conn.commit()
    conn.close()

def run_query(query, params=(), fetch=False):
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    c.execute(query, params)
    if fetch:
        data = c.fetchall()
    else:
        data = None
        conn.commit()
    conn.close()
    return data

# --- CÁLCULOS METABÓLICOS ---
def calcular_bmr_tdee(peso, altura, edad, sexo, actividad):
    # Fórmula Mifflin-St Jeor
    if sexo == "Hombre":
        bmr = (10 * peso) + (6.25 * altura) - (5 * edad) + 5
    else:
        bmr = (10 * peso) + (6.25 * altura) - (5 * edad) - 161
    
    # Factor de actividad
    factores = {
        "Sedentario (Poco o nada)": 1.2,
        "Ligero (1-3 días/sem)": 1.375,
        "Moderado (3-5 días/sem)": 1.55,
        "Activo (6-7 días/sem)": 1.725,
        "Muy Activo (Doble sesión)": 1.9
    }
    factor = factores.get(actividad, 1.2)
    tdee = bmr * factor
    return bmr, tdee

# --- SEGURIDAD ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# --- IA GENERATOR (PROMPT AVANZADO) ---
def generar_dieta_ia(perfil, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Construimos el texto con los datos técnicos
        info_tecnica = f"""
        DATOS TÉCNICOS:
        - BMR: {perfil['bmr']:.0f} kcal
        - TDEE (Mantenimiento): {perfil['tdee']:.0f} kcal
        - OBJETIVO CALÓRICO DIARIO: {perfil['calorias_objetivo']:.0f} kcal
        - OBJETIVO: {perfil['objetivo']}
        - PREFERENCIA MACROS: Proteína {perfil['prot']}g/kg, Grasas {perfil['grasa']}g/kg.
        """

        prompt = f"""
        Actúa como un nutricionista deportivo de alto nivel.
        
        {info_tecnica}
        
        ESTRUCTURA OBLIGATORIA DE LA RESPUESTA:
        
        1. **RESUMEN NUTRICIONAL**:
           - Muestra claramente el objetivo calórico y el déficit/superávit aplicado.
           - Explica brevemente por qué estas calorías.

        2. **DISTRIBUCIÓN DE MACRONUTRIENTES**:
           - Calcula los gramos totales de Proteína, Grasas y Carbohidratos para llegar a las calorías objetivo.
           - Si el usuario definió g/kg, úsalos. Si no, sugiérelos tú basándote en evidencia científica para el objetivo.
           - Muestra porcentaje aproximado (ej: 40% Prot / 30% Grasa / 30% Carbs).

        3. **PLAN SEMANAL DETALLADO**:
           - Formato LISTA (No tablas).
           - Usa este formato exacto para cada día:
             **[Día]**
             * 🍳 **Desayuno:** ... (Calorías aprox)
             * 🍎 **Snack 1:** ...
             * 🥗 **Almuerzo:** ...
             * 🥛 **Snack 2:** ...
             * 🐟 **Cena:** ...
        """
        
        with st.spinner('Calculando macros y diseñando menú...'):
            response = model.generate_content(prompt)
            return response.text
            
    except Exception as e:
        return f"Error IA: {str(e)}"

# --- INTERFAZ ---
def main():
    init_db()
    st.title("🥗 NutriApp AI v4.0")

    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    if st.session_state['logged_in']:
        menu = ["NutriAgent AI", "Recetas", "Mi Progreso", "Mi Perfil", "Cerrar Sesión"]
        st.sidebar.success(f"Usuario: {st.session_state['username']}")
    else:
        menu = ["Login", "Registro"]

    choice = st.sidebar.selectbox("Navegación", menu)

    # --- LOGIN / REGISTRO ---
    if choice == "Registro":
        st.subheader("Nuevo Usuario")
        new_user = st.text_input("Usuario")
        new_pass = st.text_input("Contraseña", type='password')
        if st.button("Crear Cuenta"):
            try:
                run_query("INSERT INTO users VALUES(?,?)", (new_user, make_hashes(new_pass)))
                st.success("Creado. Ve a Login.")
            except: st.warning("Ya existe.")

    elif choice == "Login":
        st.subheader("Acceso")
        user = st.text_input("Usuario")
        passwd = st.text_input("Contraseña", type='password')
        if st.button("Entrar"):
            if run_query("SELECT * FROM users WHERE username=? AND password=?", (user, make_hashes(passwd)), fetch=True):
                st.session_state['logged_in'] = True
                st.session_state['username'] = user
                st.rerun()
            else: st.warning("Error.")

    # --- PERFIL AVANZADO ---
    elif choice == "Mi Perfil":
        st.header("👤 Configuración Corporal")
        
        # Cargar datos
        datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        
        # Valores por defecto
        d_edad, d_peso, d_altura, d_sexo = 30, 70.0, 175, "Hombre"
        d_act = "Moderado (3-5 días/sem)"
        d_obj = "Mantenimiento"
        d_prot, d_grasa, d_carbs = 0.0, 0.0, 0.0 # 0 significa "que decida la IA"

        if datos:
            # Desempaquetar tupla (ahora tiene 10 valores)
            if len(datos[0]) == 10:
                _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_prot, d_grasa, d_carbs = datos[0]
            else:
                # Si la DB es vieja y tiene menos columnas, forzamos valores por defecto para no romper
                st.warning("⚠️ Tu base de datos es antigua. Guarda el perfil para actualizarla.")
                _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj = datos[0][:7]

        with st.form("perfil_form"):
            # 1. DATOS BÁSICOS
            st.markdown("### 1. Datos Básicos")
            c1, c2, c3, c4 = st.columns(4)
            edad = c1.number_input("Edad", value=d_edad)
            sexo = c2.selectbox("Sexo", ["Hombre", "Mujer"], index=0 if d_sexo=="Hombre" else 1)
            peso = c3.number_input("Peso (kg)", value=d_peso)
            altura = c4.number_input("Altura (cm)", value=d_altura)

            # 2. ACTIVIDAD Y OBJETIVOS
            st.markdown("### 2. Metabolismo y Objetivos")
            act_opts = ["Sedentario (Poco o nada)", "Ligero (1-3 días/sem)", "Moderado (3-5 días/sem)", "Activo (6-7 días/sem)", "Muy Activo (Doble sesión)"]
            try: act_idx = act_opts.index(d_act)
            except: act_idx = 2
            
            actividad = st.selectbox("Nivel de Actividad", act_opts, index=act_idx)
            
            obj_opts = ["Perder Grasa (Déficit)", "Mantenimiento", "Ganar Músculo (Superávit)"]
            try: obj_idx = obj_opts.index(d_obj)
            except: obj_idx = 1
            objetivo = st.selectbox("Objetivo Principal", obj_opts, index=obj_idx)

            # --- CÁLCULOS EN TIEMPO REAL (VISUALES) ---
            bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, actividad)
            cal_objetivo = tdee
            if "Perder" in objetivo: cal_objetivo -= 400
            elif "Ganar" in objetivo: cal_objetivo += 300
            
            # Mostramos los cálculos al usuario
            col_info1, col_info2, col_info3 = st.columns(3)
            col_info1.metric("Tu BMR (Basal)", f"{int(bmr)} kcal")
            col_info2.metric("Tu TDEE (Mant.)", f"{int(tdee)} kcal")
            col_info3.metric("🔥 Objetivo Diario", f"{int(cal_objetivo)} kcal", 
                             delta="-400 cal" if "Perder" in objetivo else ("+300 cal" if "Ganar" in objetivo else "0"))

            # 3. MACROS (OPCIONAL)
            st.markdown("### 3. Distribución Macros (Opcional)")
            st.caption("Deja en 0 si quieres que la IA decida lo mejor para ti.")
            cm1, cm2, cm3 = st.columns(3)
            prot_input = cm1.number_input("Proteína (g/kg peso)", value=d_prot, step=0.1)
            grasa_input = cm2.number_input("Grasas (g/kg peso)", value=d_grasa, step=0.1)
            # Carbos suele ser el resto, no hace falta pedirlo explícitamente, o puedes pedir %
            
            if st.form_submit_button("💾 Guardar Perfil Completo"):
                run_query("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)", 
                          (st.session_state['username'], edad, peso, altura, sexo, actividad, objetivo, prot_input, grasa_input, 0.0))
                # Guardar histórico peso
                run_query("INSERT INTO progress VALUES (?,?,?)", 
                          (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), peso))
                st.success("Perfil y Cálculos Guardados.")
                st.rerun()

    # --- NUTRIAGENT AI ---
    elif choice == "NutriAgent AI":
        st.header("🤖 NutriAgent AI")
        
        # Ver dieta guardada
        last = run_query("SELECT contenido, fecha, id FROM diets WHERE username=? ORDER BY id DESC LIMIT 1", (st.session_state['username'],), fetch=True)
        if last:
            if st.toggle("✏️ Editar Plan"):
                txt = st.text_area("Editor", last[0][0], height=600)
                if st.button("Guardar Cambios"):
                    run_query("UPDATE diets SET contenido=? WHERE id=?", (txt, last[0][2]))
                    st.success("Guardado"); st.rerun()
            else:
                st.caption(f"Plan del: {last[0][1]}")
                st.markdown(last[0][0])
        else: st.info("Sin plan activo.")

        st.divider()

        # Generador Nuevo
        with st.expander("✨ Generar NUEVO Plan (Con datos avanzados)"):
            datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
            if not datos or len(datos[0]) < 10:
                st.error("⚠️ Tu perfil está incompleto o desactualizado. Ve a 'Mi Perfil' y guárdalo de nuevo.")
            else:
                try: api_key = st.secrets["GOOGLE_API_KEY"]
                except: st.error("Falta API Key"); st.stop()
                
                # Recuperamos y recalculamos para asegurar precisión
                _, edad, peso, altura, sexo, act, obj, prot, grasa, _ = datos[0]
                bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, act)
                
                cal_obj = tdee
                if "Perder" in obj: cal_obj -= 400
                elif "Ganar" in obj: cal_obj += 300

                if st.button("Generar Plan Inteligente"):
                    perfil_completo = {
                        "bmr": bmr, "tdee": tdee, "calorias_objetivo": cal_obj,
                        "objetivo": obj, "prot": prot, "grasa": grasa
                    }
                    st.session_state['temp_dieta'] = generar_dieta_ia(perfil_completo, api_key)

                if 'temp_dieta' in st.session_state:
                    st.markdown(st.session_state['temp_dieta'])
                    if st.button("Confirmar y Guardar"):
                        run_query("INSERT INTO diets(username, fecha, contenido) VALUES(?,?,?)", 
                                  (st.session_state['username'], datetime.now().strftime("%Y-%m-%d %H:%M"), st.session_state['temp_dieta']))
                        del st.session_state['temp_dieta']
                        st.rerun()

    # --- RECETAS ---
    elif choice == "Recetas":
        st.header("🍳 Recetas")
        t1, t2 = st.tabs(["Mis Recetas", "Nueva"])
        with t1:
            recs = run_query("SELECT titulo, contenido, id FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
            if recs:
                for r in recs:
                    with st.expander(f"🍽️ {r[0]}"):
                        new_c = st.text_area("Edit", r[1], key=f"r{r[2]}")
                        c1, c2 = st.columns([1,4])
                        if c1.button("Save", key=f"s{r[2]}"):
                            run_query("UPDATE recipes SET contenido=? WHERE id=?", (new_c, r[2])); st.rerun()
                        if c2.button("Del", key=f"d{r[2]}"):
                            run_query("DELETE FROM recipes WHERE id=?", (r[2],)); st.rerun()
            else: st.info("Vacío")
        with t2:
            tt = st.text_input("Título"); cc = st.text_area("Contenido")
            if st.button("Guardar"):
                run_query("INSERT INTO recipes(username, titulo, contenido) VALUES(?,?,?)", (st.session_state['username'], tt, cc)); st.rerun()

    # --- PROGRESO ---
    elif choice == "Mi Progreso":
        st.header("📉 Evolución")
        dat = run_query("SELECT fecha, peso FROM progress WHERE username=?", (st.session_state['username'],), fetch=True)
        if dat: st.line_chart(pd.DataFrame(dat, columns=['Fecha','Peso']).set_index('Fecha'))
        else: st.info("No hay datos")

    elif choice == "Cerrar Sesión":
        st.session_state['logged_in'] = False; st.rerun()

if __name__ == '__main__':
    main()