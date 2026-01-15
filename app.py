import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import math
from datetime import datetime
import google.generativeai as genai

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NutriApp AI", layout="wide", page_icon="🥗")

def inject_custom_css():
    st.markdown("""
        <style>
        .stTextArea textarea { height: 60vh !important; font-size: 16px !important; }
        </style>
        """, unsafe_allow_html=True)

# --- BASE DE DATOS ---
def init_db():
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)')
    c.execute('''CREATE TABLE IF NOT EXISTS profiles
                 (username TEXT PRIMARY KEY, edad INTEGER, peso REAL, altura INTEGER, 
                  sexo TEXT, actividad TEXT, objetivo TEXT, 
                  prot_g_kg REAL, grasa_g_kg REAL, carbos_pct REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (username TEXT, fecha TEXT, peso REAL, cintura REAL, cuello REAL, cadera REAL, grasa_pct REAL)''')
    c.execute('CREATE TABLE IF NOT EXISTS diets (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, fecha TEXT, contenido TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, titulo TEXT, contenido TEXT, categoria TEXT)')
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

# --- LÓGICA MATEMÁTICA ---
def calcular_bmr_tdee(peso, altura, edad, sexo, actividad):
    if sexo == "Hombre": bmr = (10 * peso) + (6.25 * altura) - (5 * edad) + 5
    else: bmr = (10 * peso) + (6.25 * altura) - (5 * edad) - 161
    f = {"Sedentario (Poco o nada)":1.0, "Ligero (1-3 días/sem)":1.2, "Moderado (4-5 días/sem)":1.375, "Activo (5-6 días/sem)":1.55, "Muy Activo (7 o más)":1.725}
    return bmr, bmr * f.get(actividad, 1.2)

def calcular_calorias_objetivo(tdee, objetivo):
    d = {"Déficit Leve (-250 kcal)":-250, "Déficit Moderado (-400 kcal)":-400, "Mantenimiento":0, "Superávit Leve (+150 kcal)":150, "Superávit Moderado (+300 kcal)":300}
    delta = d.get(objetivo, 0)
    return tdee + delta, delta

def calcular_grasa_corporal(sexo, ci, cu, ca, al):
    try:
        if sexo == "Hombre": return 495 / (1.0324 - 0.19077 * math.log10(ci - cu) + 0.15456 * math.log10(al)) - 450
        else: return 495 / (1.29579 - 0.35004 * math.log10(ci + ca - cu) + 0.22100 * math.log10(al)) - 450
    except: return 0.0

# --- IA GENERADORES ---
def generar_receta_individual_ia(ingredientes, categoria, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"Actúa como chef experto. Crea una receta de {categoria} basada en la idea: '{ingredientes}'. Incluye título, ingredientes detallados, pasos y calorías totales."
        return model.generate_content(prompt).text
    except Exception as e: return f"Error: {str(e)}"

def generar_dieta_inteligente(perfil, recetas_db, api_key):
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        cat_map = {"Desayuno":[], "Snack 1":[], "Almuerzo":[], "Snack 2":[], "Cena":[]}
        for r in recetas_db:
            if r[1] in cat_map: cat_map[r[1]].append(r[0])
        texto_recetas = "\n".join([f"- {k}: {', '.join(v) if v else 'Ninguna'}" for k,v in cat_map.items()])

        prompt = f"""
        Nutricionista Personal. Meta: {perfil['calorias_objetivo']:.0f} kcal. 
        RECETAS GUARDADAS:
        {texto_recetas}

        1. Crea un plan semanal detallado.
        2. Formato por día (tienes que cumplir obligatoriamente esta estructura):
           **[Día]**
           * 🍳 **Desayuno:** [Nombre] ([kcal] kcal)
           * 🍎 **Snack 1:** [Nombre] ([kcal] kcal)
           * 🥗 **Almuerzo:** [Nombre] ([kcal] kcal)
           * 🥛 **Snack 2:** [Nombre] ([kcal] kcal)
           * 🐟 **Cena:** [Nombre] ([kcal] kcal)

           **🔥 Total Día: [Suma] kcal**
           ---
        
        ###NUEVAS_RECETAS###
        TITULO: [Nombre]
        CATEGORIA: [Categoría]
        CONTENIDO: [Macros y pasos]
        END_RECIPE
        """
        resp = model.generate_content(prompt).text
        nuevas = []
        if "###NUEVAS_RECETAS###" in resp:
            partes = resp.split("###NUEVAS_RECETAS###")
            dieta = partes[0].strip()
            for b in partes[1].split("END_RECIPE"):
                if "TITULO:" in b:
                    try:
                        lines = b.strip().split('\n')
                        t = next(l for l in lines if "TITULO:" in l).split(":")[1].strip()
                        c = next(l for l in lines if "CATEGORIA:" in l).split(":")[1].strip()
                        cont = b[b.find("CONTENIDO:")+10:].strip()
                        nuevas.append({"titulo":t, "categoria":c, "contenido":cont})
                    except: continue
            return dieta, nuevas
        return resp, []
    except Exception as e: return f"Error: {str(e)}", []

# --- APP ---
def main():
    init_db(); inject_custom_css()
    st.title("🥗 NutriApp AI v13.1")

    if 'logged_in' not in st.session_state: st.session_state.update({'logged_in': False, 'username': ''})
    menu = ["Mi Dieta Semanal", "Mis Recetas", "Mi Progreso", "Mi Perfil", "Cerrar Sesión"] if st.session_state['logged_in'] else ["Login", "Registro"]
    choice = st.sidebar.selectbox("Menú", menu)

    # --- PERFIL ---
    if choice == "Mi Perfil":
        st.header("👤 Configuración Corporal")
        datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_pr, d_gr = 30, 70.0, 175, "Hombre", "Moderado (4-5 días/sem)", "Mantenimiento", 0.0, 0.0
        if datos:
            if len(datos[0]) == 10: _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_pr, d_gr, _ = datos[0]
            else: _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj = datos[0][:7]

        with st.form("perfil_form"):
            st.markdown("### 1. Datos Básicos")
            c1, c2, c3, c4 = st.columns(4)
            edad = c1.number_input("Edad", value=d_edad); sexo = c2.selectbox("Sexo", ["Hombre", "Mujer"], index=0 if d_sexo=="Hombre" else 1)
            peso = c3.number_input("Peso (kg)", value=d_peso); altura = c4.number_input("Altura (cm)", value=d_altura)
            act_opts = ["Sedentario (Poco o nada)", "Ligero (1-3 días/sem)", "Moderado (4-5 días/sem)", "Activo (5-6 días/sem)", "Muy Activo (7 o más)"]
            actividad = st.selectbox("Actividad", act_opts, index=act_opts.index(d_act) if d_act in act_opts else 2)
            obj_opts = ["Déficit Leve (-250 kcal)", "Déficit Moderado (-400 kcal)", "Mantenimiento", "Superávit Leve (+150 kcal)", "Superávit Moderado (+300 kcal)"]
            objetivo = st.selectbox("Objetivo", obj_opts, index=obj_opts.index(d_obj) if d_obj in obj_opts else 2)

            bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, actividad)
            cal_obj, delta = calcular_calorias_objetivo(tdee, objetivo)
            
            ci1, ci2, ci3 = st.columns(3)
            ci1.metric("BMR (Basal)", f"{int(bmr)} kcal"); ci2.metric("TDEE (Real)", f"{int(tdee)} kcal"); ci3.metric("🔥 Meta", f"{int(cal_obj)} kcal", delta=f"{delta} kcal")

            st.markdown("### 3. Macros")
            cm1, cm2 = st.columns(2)
            prot = cm1.number_input("Proteína (g/kg)", value=d_pr); grasa = cm2.number_input("Grasas (g/kg)", value=d_gr)
            if st.form_submit_button("💾 Guardar y Recalcular"):
                run_query("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)", (st.session_state['username'], edad, peso, altura, sexo, actividad, objetivo, prot, grasa, 0.0))
                run_query("INSERT INTO progress (username, fecha, peso) VALUES (?,?,?)", (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), peso))
                st.rerun()

    # --- MIS RECETAS (Con Chef IA Restaurado) ---
    elif choice == "Mis Recetas":
        st.header("🍳 Mis Recetas")
        categorias = ["Desayuno", "Snack 1", "Almuerzo", "Snack 2", "Cena", "Otros"]
        t_ver, t_add = st.tabs(["📂 Ver Mi Libro", "➕ Añadir / Chef IA"])
        
        with t_ver:
            sub_tabs = st.tabs(categorias)
            recs = run_query("SELECT titulo, contenido, id, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
            for i, cat in enumerate(categorias):
                with sub_tabs[i]:
                    cat_recs = [r for r in recs if r[3] == cat]
                    if not cat_recs: st.info(f"Sin recetas en {cat}")
                    for r in cat_recs:
                        with st.expander(f"📖 {r[0]}"):
                            nt = st.text_input("Título", r[0], key=f"t{r[2]}")
                            nc = st.text_area("Receta", r[1], key=f"c{r[2]}")
                            if st.button("Guardar", key=f"b{r[2]}"):
                                run_query("UPDATE recipes SET titulo=?, contenido=? WHERE id=?", (nt, nc, r[2])); st.rerun()
                            if st.button("Borrar", key=f"d{r[2]}"):
                                run_query("DELETE FROM recipes WHERE id=?", (r[2],)); st.rerun()

        with t_add:
            st.subheader("Nuevo Plato")
            c_sel = st.selectbox("¿Para qué momento es?", categorias)
            
            with st.container(border=True):
                st.markdown("🤖 **Chef IA**")
                idea = st.text_input("Dime qué tienes o qué quieres (ej: 'pollo y calabacín'):")
                if st.button("Generar con IA"):
                    try: api = st.secrets["GOOGLE_API_KEY"]
                    except: st.error("Falta API Key"); st.stop()
                    st.session_state['tmp_r'] = generar_receta_individual_ia(idea, c_sel, api)
                    st.session_state['tmp_t'] = idea.split(".")[0] if len(idea) < 30 else f"Receta {c_sel}"

            t_f = st.text_input("Título Final", value=st.session_state.get('tmp_t', ''))
            c_f = st.text_area("Contenido Final", value=st.session_state.get('tmp_r', ''))
            if st.button("💾 Guardar en mi Libro"):
                run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", (st.session_state['username'], t_f, c_f, c_sel))
                if 'tmp_r' in st.session_state: del st.session_state['tmp_r']
                st.success("¡Guardada!"); st.rerun()

    # --- MI DIETA SEMANAL ---
    elif choice == "Mi Dieta Semanal":
        st.header("📅 Mi Dieta Semanal")
        last = run_query("SELECT contenido FROM diets WHERE username=? ORDER BY id DESC LIMIT 1", (st.session_state['username'],), fetch=True)
        if last: st.markdown(last[0][0])
        with st.expander("Generar Nuevo"):
            if st.button("Generar Plan"):
                p = run_query("SELECT peso, altura, edad, sexo, actividad, objetivo FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
                r = run_query("SELECT titulo, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
                if p:
                    _, tdee = calcular_bmr_tdee(p[0][0], p[0][1], p[0][2], p[0][3], p[0][4])
                    cal, _ = calcular_calorias_objetivo(tdee, p[0][5])
                    d, n = generar_dieta_inteligente({"calorias_objetivo":cal, "objetivo":p[0][5]}, r, st.secrets["GOOGLE_API_KEY"])
                    st.session_state.update({'td': d, 'tn': n}); st.markdown(d)
                else: st.warning("Rellena perfil.")
            if 'td' in st.session_state and st.button("✅ Confirmar"):
                run_query("INSERT INTO diets(username, fecha, contenido) VALUES(?,?,?)", (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), st.session_state['td']))
                for n in st.session_state['tn']: run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", (st.session_state['username'], n['titulo'], n['contenido'], n['categoria']))
                del st.session_state['td']; st.rerun()

    # --- PROGRESO ---
    elif choice == "Mi Progreso":
        st.header("📉 Mi Progreso")
        perf = run_query("SELECT sexo, altura FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        if not perf: st.warning("Configura tu perfil."); st.stop()
        with st.form("chk"):
            c1, c2, c3 = st.columns(3)
            fp = c1.number_input("Peso (kg)"); fci = c2.number_input("Cintura (cm)"); fcu = c3.number_input("Cuello (cm)")
            if st.form_submit_button("Registrar"):
                g = calcular_grasa_corporal(perf[0][0], fci, fcu, 0.0, perf[0][1])
                run_query("INSERT INTO progress VALUES (?,?,?,?,?,?,?)", (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), fp, fci, fcu, 0.0, g))
                st.rerun()
        data = run_query("SELECT fecha, peso, grasa_pct FROM progress WHERE username=? ORDER BY fecha ASC", (st.session_state['username'],), fetch=True)
        if data: st.line_chart(pd.DataFrame(data, columns=['Fecha','Peso','Grasa']).set_index('Fecha'))

    elif choice == "Login":
        u = st.text_input("User"); p = st.text_input("Pass", type='password')
        if st.button("Entrar"):
            h = hashlib.sha256(str.encode(p)).hexdigest()
            if run_query("SELECT * FROM users WHERE username=? AND password=?", (u, h), fetch=True):
                st.session_state.update({'logged_in': True, 'username': u}); st.rerun()
    elif choice == "Registro":
        u = st.text_input("User"); p = st.text_input("Pass", type='password')
        if st.button("Registrar"): run_query("INSERT INTO users VALUES(?,?)", (u, hashlib.sha256(str.encode(p)).hexdigest())); st.success("Ok")
    elif choice == "Cerrar Sesión":
        st.session_state.update({'logged_in': False, 'username': ''}); st.rerun()

if __name__ == '__main__': main()