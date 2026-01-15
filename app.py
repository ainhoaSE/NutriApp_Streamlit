import streamlit as st
import pandas as pd
import sqlite3
import hashlib
import math
import re
from datetime import datetime
from fpdf import FPDF
from google import genai # Nueva librería oficial

# --- CONFIGURACIÓN ---
st.set_page_config(page_title="NutriApp AI", layout="wide", page_icon="🥗")

def inject_custom_css():
    st.markdown("""
        <style>
        .stTextArea textarea { height: 60vh !important; font-size: 16px !important; }
        </style>
        """, unsafe_allow_html=True)


def generar_pdf_dieta(contenido_dieta, nombre_usuario):
    # Forzamos A4 y márgenes de 10mm
    pdf = FPDF(orientation='P', unit='mm', format='A4')
    pdf.set_margins(10, 10, 10)
    pdf.add_page()
    
    # Calculamos el ancho real de escritura (Ancho total - margenes)
    ancho_util = pdf.w - 20 

    # --- CABECERA SUPER COMPACTA ---
    pdf.set_fill_color(230, 240, 230) 
    pdf.set_font("helvetica", "B", 14)
    # Usamos ancho_util en lugar de 0 para evitar el error de espacio
    pdf.cell(ancho_util, 10, f"DIETA SEMANAL: {nombre_usuario.upper()}", ln=True, align="C", fill=True)
    
    pdf.set_font("helvetica", "I", 8)
    pdf.cell(ancho_util, 5, f"Generado el: {datetime.now().strftime('%d/%m/%Y')}", ln=True, align="R")
    pdf.ln(1)
    
    # --- PROCESAMIENTO SEGURO ---
    # Latin-1 para tildes y eñes, ignorando emojis
    texto_limpio = contenido_dieta.encode('latin-1', 'replace').decode('latin-1')
    texto_limpio = texto_limpio.replace('*', '').replace('\t', ' ') 

    dias_semana = ["LUNES", "MARTES", "MIERCOLES", "MIÉRCOLES", "JUEVES", "VIERNES", "SABADO", "SÁBADO", "DOMINGO"]
    
    for linea in texto_limpio.splitlines():
        linea = linea.strip()
        if not linea:
            continue 
            
        # Siempre reseteamos X al margen izquierdo antes de escribir nada
        pdf.set_x(10)

        # 1. DETECCIÓN DE DÍA
        if any(linea.upper().startswith(dia) for dia in dias_semana):
            pdf.ln(1)
            pdf.set_font("helvetica", "B", 10)
            pdf.set_fill_color(200, 220, 200)
            pdf.cell(ancho_util, 6, f" {linea.upper()}", ln=True, fill=True)
            pdf.set_font("helvetica", "", 9)
        
        # 2. DETECCIÓN DE TOTALES
        elif "TOTAL D" in linea.upper() or "PROMEDIO" in linea.upper():
            pdf.set_font("helvetica", "B", 8)
            pdf.set_text_color(150, 0, 0)
            pdf.cell(ancho_util, 5, f"      {linea}", ln=True)
            pdf.set_text_color(0, 0, 0)
            
        # 3. PLATOS (USO DE MULTI_CELL SEGURO)
        else:
            pdf.set_font("helvetica", "", 9)
            # multi_cell con ancho_util es la forma más segura de evitar el error de espacio
            pdf.multi_cell(ancho_util, 5, f"- {linea}", border=0)
            
    return bytes(pdf.output())

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

# --- LÓGICA METABÓLICA (Mifflin-St Jeor) ---
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

def make_hashes(password): return hashlib.sha256(str.encode(password)).hexdigest()

# --- NUEVA LÓGICA IA (google-genai) ---
def get_ai_client():
    return genai.Client(api_key=st.secrets["GOOGLE_API_KEY"])

def generar_receta_ia(idea, categoria):
    client = get_ai_client()
    prompt = f"Actúa como chef. Crea una receta de {categoria} basada en: {idea}. Incluye títulos, pasos y calorías."
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return response.text

def generar_dieta_ia(perfil, recetas_db):
    client = get_ai_client()
    cat_map = {"Desayuno":[], "Snack 1":[], "Almuerzo":[], "Snack 2":[], "Cena":[]}
    for r in recetas_db:
        if r[1] in cat_map: cat_map[r[1]].append(r[0])
    
    txt_recetas = "\n".join([f"- {k}: {', '.join(v) if v else 'Ninguna'}" for k,v in cat_map.items()])
    
    prompt = f"""
    Nutricionista. Meta: {perfil['calorias_objetivo']:.0f} kcal.
    Recetas del usuario: {txt_recetas}
    Genera plan Lunes-Domingo. Formato:
    **[Día]**
    * 🍳 **Desayuno:** [Plato] ([kcal] kcal)
    * 🍎 **Snack 1:** ...
    * 🥗 **Almuerzo:** ...
    * 🥛 **Snack 2:** ...
    * 🐟 **Cena:** ...
    **🔥 Total Día: [Suma] kcal**
    ---
    ###NUEVAS_RECETAS###
    TITULO: [Nombre]
    CATEGORIA: [Cat]
    CONTENIDO: [Pasos]
    END_RECIPE
    """
    response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    resp_text = response.text
    
    nuevas = []
    if "###NUEVAS_RECETAS###" in resp_text:
        partes = resp_text.split("###NUEVAS_RECETAS###")
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
    return resp_text, []

# --- APP ---
def main():
    init_db(); inject_custom_css()
    st.title("🥗 NutriApp AI v15.0")

    if 'logged_in' not in st.session_state: st.session_state.update({'logged_in': False, 'username': ''})
    menu = ["Mi Dieta Semanal", "Mis Recetas", "Mi Progreso", "Mi Perfil", "Cerrar Sesión"] if st.session_state['logged_in'] else ["Login", "Registro"]
    choice = st.sidebar.selectbox("Navegación", menu)

    # --- MI DIETA SEMANAL ---
    if choice == "Mi Dieta Semanal":
        st.header("📅 Mi Dieta Semanal")
        
        last = run_query("SELECT contenido FROM diets WHERE username=? ORDER BY id DESC LIMIT 1", (st.session_state['username'],), fetch=True)
        
        if last:
            st.markdown(last[0][0])
            st.divider()
            
            try:
                # Generamos los bytes inmutables
                pdf_bytes = generar_pdf_dieta(last[0][0], st.session_state['username'])
                
                st.download_button(
                    label="📥 Descargar Dieta en PDF",
                    data=pdf_bytes,
                    file_name=f"Dieta_{st.session_state['username']}.pdf",
                    mime="application/pdf",
                    key="download_pdf_btn" # Añadimos una key única por seguridad
                )
            except Exception as e:
                st.error(f"Error al generar el PDF: {e}")
        
        else:
            st.info("No tienes ninguna dieta guardada actualmente. ¡Genera una nueva abajo!")

        # 3. Debajo de todo aparece el expansor para crear planes nuevos
        with st.expander("✨ Nuevo Plan"):
            if st.button("Generar Plan Semanal"):
                p = run_query("SELECT peso, altura, edad, sexo, actividad, objetivo FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
                r = run_query("SELECT titulo, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
                if p:
                    _, tdee = calcular_bmr_tdee(p[0][0], p[0][1], p[0][2], p[0][3], p[0][4])
                    cal, _ = calcular_calorias_objetivo(tdee, p[0][5])
                    d, n = generar_dieta_ia({"calorias_objetivo": cal}, r)
                    st.session_state.update({'td': d, 'tn': n}); st.rerun()
            
            if 'td' in st.session_state:
                st.markdown(st.session_state['td'])
                if st.button("✅ Confirmar y Guardar"):
                    run_query("INSERT INTO diets(username, fecha, contenido) VALUES(?,?,?)", (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), st.session_state['td']))
                    for n in st.session_state['tn']: run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", (st.session_state['username'], n['titulo'], n['contenido'], n['categoria']))
                    del st.session_state['td']; st.rerun()

    # --- MIS RECETAS ---
    elif choice == "Mis Recetas":
        st.header("🍳 Mis Recetas")
        categorias = ["Desayuno", "Snack 1", "Almuerzo", "Snack 2", "Cena", "Otros"]
        t_ver, t_add = st.tabs(["📂 Ver Mi Libro", "➕ Añadir / Chef IA"])
        with t_ver:
            sub_tabs = st.tabs(categorias)
            recs = run_query("SELECT titulo, contenido, id, categoria FROM recipes WHERE username=?", (st.session_state['username'],), fetch=True)
            for i, cat in enumerate(categorias):
                with sub_tabs[i]:
                    for r in [x for x in recs if x[3] == cat]:
                        with st.expander(f"📖 {r[0]}"):
                            nt = st.text_input("Título", r[0], key=f"t{r[2]}")
                            nc = st.text_area("Receta", r[1], key=f"c{r[2]}")
                            if st.button("Guardar", key=f"b{r[2]}"): run_query("UPDATE recipes SET titulo=?, contenido=? WHERE id=?", (nt, nc, r[2])); st.rerun()
                            if st.button("Borrar", key=f"d{r[2]}"): run_query("DELETE FROM recipes WHERE id=?", (r[2],)); st.rerun()
        with t_add:
            c_sel = st.selectbox("Categoría", categorias)
            idea = st.text_input("Idea para Chef IA:")
            if st.button("Generar con IA"):
                st.session_state['tmp_r'] = generar_receta_ia(idea, c_sel)
                st.session_state['tmp_t'] = idea.split(".")[0]
            tf = st.text_input("Nombre", value=st.session_state.get('tmp_t', ''))
            cf = st.text_area("Contenido", value=st.session_state.get('tmp_r', ''))
            if st.button("Guardar"): run_query("INSERT INTO recipes(username, titulo, contenido, categoria) VALUES(?,?,?,?)", (st.session_state['username'], tf, cf, c_sel)); st.rerun()

    # --- MI PROGRESO ---
    elif choice == "Mi Progreso":
        st.header("📉 Seguimiento Corporal")
        perf = run_query("SELECT sexo, altura FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        if not perf: st.warning("Rellena el perfil."); st.stop()
        with st.form("chk"):
            c1, c2, c3, c4 = st.columns(4)
            fp = c1.number_input("Peso (kg)"); fci = c2.number_input("Cintura (cm)"); fcu = c3.number_input("Cuello (cm)")
            fca = c4.number_input("Cadera (mujeres)", value=0.0) if perf[0][0] == "Mujer" else 0.0
            if st.form_submit_button("Registrar"):
                g = calcular_grasa_corporal(perf[0][0], fci, fcu, fca, perf[0][1])
                run_query("INSERT INTO progress VALUES (?,?,?,?,?,?,?)", (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), fp, fci, fcu, fca, g))
                st.rerun()
        data = run_query("SELECT fecha, peso, grasa_pct FROM progress WHERE username=? ORDER BY fecha ASC", (st.session_state['username'],), fetch=True)
        if data: st.line_chart(pd.DataFrame(data, columns=['Fecha','Peso','Grasa']).set_index('Fecha'))

    # --- MI PERFIL ---
    elif choice == "Mi Perfil":
        st.header("👤 Configuración Corporal")
        datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        
        # Valores por defecto
        d_edad, d_peso, d_altura, d_sexo = 30, 70.0, 175, "Hombre"
        d_act, d_obj, d_pr, d_gr = "Moderado (4-5 días/sem)", "Mantenimiento", 0.0, 0.0

        if datos:
            # Manejo de compatibilidad de versiones de la base de datos
            if len(datos[0]) == 10: 
                _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj, d_pr, d_gr, _ = datos[0]
            else: 
                _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj = datos[0][:7]

        with st.form("perfil_form"):
            st.markdown("### 1. Datos Básicos")
            c1, c2, c3, c4 = st.columns(4)
            edad = c1.number_input("Edad", value=d_edad)
            sexo = c2.selectbox("Sexo", ["Hombre", "Mujer"], index=0 if d_sexo=="Hombre" else 1)
            peso = c3.number_input("Peso (kg)", value=d_peso)
            altura = c4.number_input("Altura (cm)", value=d_altura)

            st.markdown("### 2. Metabolismo")
            act_opts = [
                "Sedentario (Poco o nada)", 
                "Ligero (1-3 días/sem)", 
                "Moderado (4-5 días/sem)", 
                "Activo (5-6 días/sem)", 
                "Muy Activo (7 o más)"
            ]
            actividad = st.selectbox("Nivel de Actividad", act_opts, index=act_opts.index(d_act) if d_act in act_opts else 2)
            
            obj_opts = [
                "Déficit Leve (-250 kcal)", 
                "Déficit Moderado (-400 kcal)", 
                "Mantenimiento", 
                "Superávit Leve (+150 kcal)", 
                "Superávit Moderado (+300 kcal)"
            ]
            objetivo = st.selectbox("Objetivo Principal", obj_opts, index=obj_opts.index(d_obj) if d_obj in obj_opts else 2)

            # --- CÁLCULOS VISUALES EN TIEMPO REAL ---
            bmr, tdee = calcular_bmr_tdee(peso, altura, edad, sexo, actividad)
            cal_obj, delta = calcular_calorias_objetivo(tdee, objetivo)
            
            ci1, ci2, ci3 = st.columns(3)
            ci1.metric("BMR (Basal)", f"{int(bmr)} kcal")
            ci2.metric("TDEE (Real)", f"{int(tdee)} kcal")
            ci3.metric("🔥 Meta Diaria", f"{int(cal_obj)} kcal", delta=f"{delta} kcal" if delta != 0 else None)

            st.markdown("### 3. Macros Personalizados (Opcional)")
            st.caption("Pon 0 para que la IA decida automáticamente.")
            cm1, cm2 = st.columns(2)
            prot = cm1.number_input("Proteína (g/kg)", value=d_pr, step=0.1)
            grasa = cm2.number_input("Grasas (g/kg)", value=d_gr, step=0.1)
            
            if st.form_submit_button("💾 Guardar y Recalcular"):
                # Guardar en la tabla profiles
                run_query("INSERT OR REPLACE INTO profiles VALUES (?,?,?,?,?,?,?,?,?,?)", 
                          (st.session_state['username'], edad, peso, altura, sexo, actividad, objetivo, prot, grasa, 0.0))
                
                # Sincronizar el peso con la tabla de progreso
                run_query("INSERT INTO progress (username, fecha, peso) VALUES (?,?,?)", 
                          (st.session_state['username'], datetime.now().strftime("%Y-%m-%d"), peso))
                
                st.success("Perfil actualizado correctamente.")
                st.rerun()
    # --- LOGIN / REGISTRO / LOGOUT ---
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