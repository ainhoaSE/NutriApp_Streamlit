import streamlit as st
import pandas as pd
import sqlite3
import hashlib
from datetime import datetime
import time

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="NutriApp AI", layout="wide")

# --- GESTIÓN DE BASE DE DATOS (SQLite Local) ---
def init_db():
    conn = sqlite3.connect('nutriapp.db')
    c = conn.cursor()
    # Tabla de usuarios
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT)''')
    # Tabla de perfiles
    c.execute('''CREATE TABLE IF NOT EXISTS profiles
                 (username TEXT PRIMARY KEY, edad INTEGER, peso REAL, altura INTEGER, 
                  sexo TEXT, actividad TEXT, objetivo TEXT)''')
    # Tabla de progreso (peso)
    c.execute('''CREATE TABLE IF NOT EXISTS progress
                 (username TEXT, fecha TEXT, peso REAL)''')
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

# --- FUNCIONES DE SEGURIDAD (Simples) ---
def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

def check_hashes(password, hashed_text):
    if make_hashes(password) == hashed_text:
        return True
    return False

# --- LÓGICA DE LA IA (SIMULADA POR AHORA) ---
def generar_dieta_ia(perfil):
    """
    Aquí conectaremos la API de Gemini real más adelante.
    Por ahora, simula que piensa y devuelve un plan genérico.
    """
    with st.spinner('La IA está analizando tu perfil y calculando macros...'):
        time.sleep(2) # Simula tiempo de pensamiento
    
    return f"""
    ### 🥗 Plan Semanal para: {perfil['objetivo']}
    **Perfil:** {perfil['peso']}kg | {perfil['actividad']}
    
    **Lunes:**
    * 🍳 **Desayuno:** Tortilla francesa (2 huevos), 1 tostada integral, café solo.
    * 🍎 **Snack 1:** Una manzana y un puñado de nueces.
    * 🥗 **Almuerzo:** Ensalada de quinoa con pollo a la plancha y aguacate.
    * 🥛 **Snack 2:** Yogur griego natural sin azúcar.
    * 🐟 **Cena:** Merluza al horno con espárragos trigueros.
    
    *(Nota: Este es un ejemplo. Cuando conectemos la API key, esto será personalizado)*
    """

# --- INTERFAZ PRINCIPAL ---
def main():
    init_db()
    
    st.title("🥗 NutriApp AI: Tu Nutricionista Personal")

    # Sidebar para navegación
    menu = ["Login", "Registro"]
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    if st.session_state['logged_in']:
        menu = ["Mi Perfil", "Generador de Dieta", "Mi Progreso", "Cerrar Sesión"]
        st.sidebar.success(f"Hola, {st.session_state['username']}")

    choice = st.sidebar.selectbox("Menú", menu)

    # --- SECCIÓN REGISTRO ---
    if choice == "Registro":
        st.subheader("Crear Nueva Cuenta")
        new_user = st.text_input("Usuario")
        new_password = st.text_input("Contraseña", type='password')
        if st.button("Registrarse"):
            try:
                run_query("INSERT INTO users(username, password) VALUES(?,?)", 
                          (new_user, make_hashes(new_password)))
                st.success("¡Cuenta creada! Ve al menú de Login.")
            except:
                st.warning("Ese usuario ya existe.")

    # --- SECCIÓN LOGIN ---
    elif choice == "Login":
        st.subheader("Iniciar Sesión")
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type='password')
        if st.button("Entrar"):
            result = run_query("SELECT * FROM users WHERE username = ? AND password = ?", 
                               (username, make_hashes(password)), fetch=True)
            if result:
                st.session_state['logged_in'] = True
                st.session_state['username'] = username
                st.rerun()
            else:
                st.warning("Usuario o contraseña incorrectos")

    # --- SECCIÓN PERFIL ---
    elif choice == "Mi Perfil":
        st.subheader("Configura tus datos físicos")
        # Intentar cargar datos previos
        datos_previos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        
        # Valores por defecto
        d_edad, d_peso, d_altura = 30, 70.0, 170
        d_sexo, d_act, d_obj = "Hombre", "Moderado", "Mantenimiento"
        
        if datos_previos:
            _, d_edad, d_peso, d_altura, d_sexo, d_act, d_obj = datos_previos[0]

        with st.form("perfil_form"):
            col1, col2 = st.columns(2)
            with col1:
                edad = st.number_input("Edad", value=d_edad)
                peso = st.number_input("Peso (kg)", value=d_peso)
                altura = st.number_input("Altura (cm)", value=d_altura)
            with col2:
                sexo = st.selectbox("Sexo", ["Hombre", "Mujer"], index=0 if d_sexo=="Hombre" else 1)
                actividad = st.selectbox("Actividad", ["Sedentario", "Ligero", "Moderado", "Intenso"], index=["Sedentario", "Ligero", "Moderado", "Intenso"].index(d_act))
                objetivo = st.selectbox("Objetivo", ["Perder Grasa", "Ganar Músculo", "Mantenimiento"], index=["Perder Grasa", "Ganar Músculo", "Mantenimiento"].index(d_obj))
            
            submitted = st.form_submit_button("Guardar Perfil")
            
            if submitted:
                # Guardar o actualizar perfil
                run_query("INSERT OR REPLACE INTO profiles VALUES (?, ?, ?, ?, ?, ?, ?)", 
                          (st.session_state['username'], edad, peso, altura, sexo, actividad, objetivo))
                # Guardar peso en histórico también
                fecha_hoy = datetime.now().strftime("%Y-%m-%d")
                run_query("INSERT INTO progress VALUES (?, ?, ?)", (st.session_state['username'], fecha_hoy, peso))
                st.success("Perfil actualizado correctamente")

    # --- SECCIÓN GENERADOR IA ---
    elif choice == "Generador de Dieta":
        st.subheader("🤖 Tu Nutricionista IA")
        
        # Cargar datos del perfil para dárselos a la IA
        datos = run_query("SELECT * FROM profiles WHERE username=?", (st.session_state['username'],), fetch=True)
        
        if not datos:
            st.warning("Por favor, rellena tu perfil primero.")
        else:
            perfil_dict = {
                "peso": datos[0][2],
                "actividad": datos[0][5],
                "objetivo": datos[0][6]
            }
            if st.button("Generar Plan Semanal"):
                plan = generar_dieta_ia(perfil_dict)
                st.markdown(plan)

    # --- SECCIÓN PROGRESO ---
    elif choice == "Mi Progreso":
        st.subheader("📉 Evolución de tu peso")
        data = run_query("SELECT fecha, peso FROM progress WHERE username=?", (st.session_state['username'],), fetch=True)
        
        if data:
            df = pd.DataFrame(data, columns=['Fecha', 'Peso'])
            st.line_chart(df.set_index('Fecha'))
            st.dataframe(df)
        else:
            st.info("Aún no hay registros de peso.")

    elif choice == "Cerrar Sesión":
        st.session_state['logged_in'] = False
        st.rerun()

if __name__ == '__main__':
    main()