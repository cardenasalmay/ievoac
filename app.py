from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
import mysql.connector
import os
from datetime import datetime, date
from io import BytesIO
import pandas as pd
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = 'clave_secreta' # Necesaria para usar sesiones y flash

# Configuración de conexión a la base de datos SECRET_KEY FUNDA25IEVO20
db_config = {
    'host': os.environ['DB_HOST'],
    'user': os.environ['DB_USER'],
    'password': os.environ['DB_PASS'],
    'database': os.environ['DB_NAME']
}

# Establecer conexión con la base de datos
db = mysql.connector.connect(**db_config)

# Crear carpeta para almacenar PDFs si no existe
os.makedirs('static/pdf', exist_ok=True)

# Inicializar contador de intentos por usuario
intentos = {}


# -----------------------------------------------
# RUTA: Login
# -----------------------------------------------
@app.route('/', methods=['GET', 'POST'])
def login():
    global intentos
    if request.method == 'POST':
        nombre = request.form['nombre']
        contrasena = request.form['contrasena']

        if nombre not in intentos:
            intentos[nombre] = 0

        # Validar credenciales especiales
        if (nombre == 'admin' and contrasena == 'admin25fievo') or (nombre == 'invitado' and contrasena == 'invi25fievo'):
            session['usuario'] = nombre
            intentos[nombre] = 0
            return redirect(url_for('registro'))

        # Validar usuario en base de datos
        cursor = db.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE nombre = %s", (nombre,))
        usuario = cursor.fetchone()

        if usuario and usuario[2] == contrasena:
            session['usuario'] = nombre
            intentos[nombre] = 0
            return redirect(url_for('registro'))
        else:
            intentos[nombre] += 1
            flash(f'Credenciales incorrectas. Intento {intentos[nombre]} de 3.', 'error')
            if intentos[nombre] >= 3:
                flash('Demasiados intentos. Acceso bloqueado.', 'error')
                return render_template('login.html', bloqueado=True)

    return render_template('login.html')

# -----------------------------------------------
# RUTA: Página principal de registros (protegida)
# -----------------------------------------------
@app.route('/registro')
def registro():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    return render_template('reg.html')

# -----------------------------------------------
# RUTA: Guardar nuevo expediente
# -----------------------------------------------
@app.route('/registrar', methods=['POST'])
def registrar():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    datos = request.form
    archivo = request.files['archivo_pdf']
    nombre_archivo = archivo.filename

    # Validar que el archivo sea menor o igual a 250 KB
    if archivo:
        contenido = archivo.read()
        if len(contenido) > 256000:
            flash('El archivo PDF no debe exceder los 250 KB.', 'error')
            return redirect(url_for('registro'))
        archivo.seek(0)

        ruta_base = os.path.join("static/pdf", nombre_archivo)

        # Renombrar si ya existe un archivo con ese nombre
        if os.path.exists(ruta_base):
            nombre_sin_ext, extension = os.path.splitext(nombre_archivo)
            contador = 1
            nueva_ruta = ruta_base
            while os.path.exists(nueva_ruta):
                nuevo_nombre = f"{nombre_sin_ext}_{contador}{extension}"
                nueva_ruta = os.path.join("static/pdf", nuevo_nombre)
                contador += 1
            archivo.save(nueva_ruta)
            nombre_archivo = os.path.basename(nueva_ruta)
        else:
            archivo.save(ruta_base)

        
    # Calculo de edad de acuerdo a la fecha de nacimiento
    fecha_nacimiento = datetime.strptime(datos['fecha_nacimiento'], '%Y-%m-%d').date()
    hoy = date.today()
    edad = hoy.year - fecha_nacimiento.year - ((hoy.month, hoy.day) < (fecha_nacimiento.month, fecha_nacimiento.day))

    # Insertar datos en la base de datos
    cursor = db.cursor()
    sql = """
        INSERT INTO expedientes (
            nombre, curp, fecha_nac, edad, talla, sexo, status,
            tutor, domicilio, telefono, diagnostico, hospital,
            archivo_pdf, fecha_registro
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
    """
    valores = (
        datos['nombre'], datos['curp'], datos['fecha_nacimiento'], edad,
        datos['talla'], datos['sexo'], datos['status'], datos['tutor'],
        datos['domicilio'], datos['telefono'], datos['diagnostico'],
        datos['hospital'], nombre_archivo
    )
    cursor.execute(sql, valores)
    db.commit()
    return redirect(url_for('consultar'))

# -----------------------------------------------
# RUTA: Consultar expedientes (protegida)
# -----------------------------------------------
@app.route('/consultar', methods=['GET', 'POST'])
def consultar():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    cursor = db.cursor()

    # Si se ha enviado el formulario de búsqueda
    if request.method == 'POST':
        filtro = request.form['filtro']
        query = """
            SELECT * FROM expedientes
            WHERE nombre LIKE %s OR curp LIKE %s
        """
        valores = (f"%{filtro}%", f"%{filtro}%")
        cursor.execute(query, valores)
    else:
        # Consulta general sin filtro
        cursor.execute("SELECT * FROM expedientes")

    expedientes = cursor.fetchall()
    return render_template('tabla.html', expedientes=expedientes)

# -----------------------------------------------
# RUTA: Editar expediente
# -----------------------------------------------
@app.route('/editareg/<int:id>', methods=['GET'])
def editar(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    cursor = db.cursor()
    cursor.execute("SELECT * FROM expedientes WHERE id = %s", (id,))
    expediente = cursor.fetchone()
    return render_template('editareg.html', expediente=expediente)

# -----------------------------------------------
# RUTA: Actualizar expediente
# -----------------------------------------------
@app.route('/actualizar/<int:id>', methods=['POST'])
def actualizar(id):
    datos = request.form
    archivo = request.files.get('archivo_pdf')
    cursor = db.cursor()

    # Obtener nombre anterior del archivo
    cursor.execute("SELECT archivo_pdf FROM expedientes WHERE id = %s", (id,))
    resultado = cursor.fetchone()
    nombre_archivo_antiguo = resultado[0] if resultado else None
    nombre_archivo_nuevo = nombre_archivo_antiguo

    # Si se cargó un nuevo archivo
    if archivo and archivo.filename != '':
        contenido = archivo.read()
        if len(contenido) > 256000:
            flash('El archivo PDF no debe exceder los 250 KB.', 'error')
            return redirect(url_for('editar', id=id))
        archivo.seek(0)

        # Eliminar el archivo anterior si existe
        if nombre_archivo_antiguo:
            ruta_anterior = os.path.join("static/pdf", nombre_archivo_antiguo)
            if os.path.exists(ruta_anterior):
                os.remove(ruta_anterior)

        # Guardar el nuevo archivo
        nombre_archivo = archivo.filename
        ruta_base = os.path.join("static/pdf", nombre_archivo)
        
        # Evitar sobrescribir archivos con el mismo nombre
        if os.path.exists(ruta_base):
            nombre_sin_ext, extension = os.path.splitext(nombre_archivo)
            contador = 1
            nueva_ruta = ruta_base
            while os.path.exists(nueva_ruta):
                nuevo_nombre = f"{nombre_sin_ext}_{contador}{extension}"
                nueva_ruta = os.path.join("static/pdf", nuevo_nombre)
                contador += 1
            archivo.save(nueva_ruta)
            nombre_archivo_nuevo = os.path.basename(nueva_ruta)
        else:
            archivo.save(ruta_base)
            nombre_archivo_nuevo = nombre_archivo

    # Actualizar campos del expediente
    sql = """
        UPDATE expedientes SET nombre=%s, curp=%s, fecha_nac=%s, talla=%s, sexo=%s, status=%s,
        tutor=%s, domicilio=%s, telefono=%s, diagnostico=%s, hospital=%s, archivo_pdf=%s
        WHERE id=%s
    """
    valores = (
        datos['nombre'], datos['curp'], datos['fecha_nacimiento'], datos['talla'],
        datos['sexo'], datos['status'], datos['tutor'], datos['domicilio'],
        datos['telefono'], datos['diagnostico'], datos['hospital'], nombre_archivo_nuevo, id
    )
    cursor.execute(sql, valores)
    db.commit()
    #flash("Expediente actualizado correctamente.", "info")
    return redirect(url_for('consultar'))


#-----------------------------------------
# Borrar registro (solo para admin)
# -----------------------------------------------
@app.route('/eliminar/<int:id>')
def eliminar(id):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    # Solo el administrador puede eliminar un registro en usuario invitano no tiene acceso permitido para borrar
    if session['usuario'] != 'admin':
        flash('No tienes permiso para eliminar registros.', 'error')
        return redirect(url_for('consultar'))

    cursor = db.cursor()
    
    # Opcional: eliminar archivo PDF del sistema
    cursor.execute("SELECT archivo_pdf FROM expedientes WHERE id = %s", (id,))
    archivo = cursor.fetchone()
    if archivo:
        ruta_pdf = os.path.join('static/pdf', archivo[0])
        if os.path.exists(ruta_pdf):
            os.remove(ruta_pdf)

    # Eliminar el registro de la base de datos
    cursor.execute("DELETE FROM expedientes WHERE id = %s", (id,))
    db.commit()

    flash('Expediente eliminado correctamente.', 'info')
    return redirect(url_for('consultar'))





#-----------------------------------------
# Generar reporte
#-----------------------------------------
# -----------------------------------------------
# RUTA: Página de generación de reportes
# -----------------------------------------------
@app.route('/greportes') 
def greportes():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    if session['usuario'] == 'invitado':
        # Aquí eliminamos el flash para que no muestre el mensaje
        return redirect(url_for('registro'))

    cursor = db.cursor()
    cursor.execute("SELECT * FROM expedientes")
    expedientes = cursor.fetchall()
    return render_template('greportes.html', expedientes=expedientes)

#@app.route('/greportes')
#def greportes():
    #if 'usuario' not in session:
    #    return redirect(url_for('login'))
    #cursor = db.cursor()
    #cursor.execute("SELECT * FROM expedientes")
    #expedientes = cursor.fetchall()
    #return render_template('greportes.html', expedientes=expedientes)


@app.route('/generar_reporte', methods=['GET'])
def generar_reporte():
    tipo = request.args.get('tipo')
    if tipo == 'pdf':
        return redirect(url_for('exportar_pdf'))
    elif tipo == 'excel':
        return redirect(url_for('exportar_excel'))
    else:
        flash("Tipo de reporte no válido.", "error")
        return redirect(url_for('greportes'))

# -----------------------------------------
# Exportar reporte a PDF
# -----------------------------------------

@app.route('/exportar_pdf')
def exportar_pdf():
    cursor = db.cursor()
    cursor.execute("SELECT * FROM expedientes")
    datos = cursor.fetchall()

    total_registros = len(datos)

    columnas = [
        'ID', 'Nombre', 'CURP', 'Fecha Nac.', 'Edad', 'Talla', 'Sexo', 'Status',
        'Tutor', 'Domicilio', 'Teléfono', 'Diagnóstico', 'Hospital', 'Archivo', 'Fecha Reg.'
    ]
    col_widths = [10, 45, 40, 20, 10, 10, 13, 13, 40, 35, 25, 45, 30, 22, 28]

    pdf = FPDF(orientation='L', unit='mm', format='A3')
    pdf.add_page()

    # Imagen
    img_path = r'C:\Users\Lenovo\Desktop\Med\proyecto - copia\static\img\ievo.png'
    if os.path.exists(img_path):
        pdf.image(img_path, x=10, y=10, w=30)

    # Título
    pdf.set_font("Arial", "B", 16)
    pdf.set_xy(45, 12)
    pdf.cell(0, 10, "Registro de expedientes digitales para beneficiarios.", ln=1)
    pdf.set_x(45)
    pdf.cell(0, 10, "Fundación I-EVO A.C. Atlacomulco", ln=1)
    pdf.ln(10)

    # Encabezado
    pdf.set_font("Arial", "B", 8)
    for i in range(len(columnas)):
        pdf.cell(col_widths[i], 10, columnas[i], 1, 0, 'C')
    pdf.ln()

    # Cuerpo
    pdf.set_font("Arial", "", 7)
    row_height = 8
    reserved_space = 60  # espacio reservado para firmas y pie de página
    for fila in datos:
        # Verifica si hay espacio suficiente en la hoja actual antes de escribir la fila
        if pdf.get_y() + row_height + reserved_space > pdf.h:
            pdf.add_page()
            # Reimprimir encabezado en la nueva página
            pdf.set_font("Arial", "B", 8)
            for i in range(len(columnas)):
                pdf.cell(col_widths[i], 10, columnas[i], 1, 0, 'C')
            pdf.ln()
            pdf.set_font("Arial", "", 7)

        for i, item in enumerate(fila):
            texto = str(item)
            if len(texto) > 50:
                texto = texto[:48] + '...'
            pdf.cell(col_widths[i], row_height, texto, 1)
        pdf.ln()

    # Firmas
    pdf.set_y(pdf.h - 55)  # 40 mm desde el final
    pdf.set_font("Arial", "", 10)
    pdf.set_x(45)
    pdf.cell(90, 6, "____________________________________", ln=1, align='C')
    pdf.set_x(45)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(90, 5, "Responsable de área", ln=1, align='C')

    pdf.set_y(pdf.get_y() - 11)
    pdf.set_x(310)
    pdf.set_font("Arial", "", 10)
    pdf.cell(90, 6, "____________________________________", ln=1, align='C')
    pdf.set_x(310)
    pdf.set_font("Arial", "B", 9)
    pdf.cell(90, 5, "Presidenta de Fundación I-EVO", ln=1, align='C')
    pdf.set_font("Arial", "", 9)
    pdf.set_x(310)
    pdf.cell(90, 5, "Lic. Marisol de la Cruz Martinez", ln=1, align='C')

    pdf.ln(4)  # Espacio extra entre el nombre y la siguiente línea

    # Total y vigencia en la misma línea
    pdf.set_font("Arial", "I", 9)
    fecha_actual = datetime.now().strftime("%d/%m/%Y")
    
    pdf.set_x(10)
    pdf.cell(0, 5, f"Total de registros: {total_registros}", align='L')
    pdf.set_x(pdf.w - 70)
    pdf.cell(60, 5, f"Vigencia: {fecha_actual}", align='R')

    # Exportar PDF
    pdf_bytes = pdf.output(dest='S').encode('latin1')
    return send_file(BytesIO(pdf_bytes), download_name="reporte_expedientes.pdf", as_attachment=True)






# -----------------------------------------
# Exportar reporte a Excel
# -----------------------------------------

@app.route('/exportar_excel')
def exportar_excel():
    cursor = db.cursor()
    cursor.execute("SELECT * FROM expedientes")
    datos = cursor.fetchall()

    columnas = [
        'ID', 'Nombre', 'CURP', 'Fecha Nac.', 'Edad', 'Talla', 'Sexo', 'Status',
        'Tutor', 'Domicilio', 'Teléfono', 'Diagnóstico', 'Hospital', 'Archivo', 'Fecha Reg.'
    ]

    df = pd.DataFrame(datos, columns=columnas)
    excel_output = BytesIO()
    df.to_excel(excel_output, index=False)
    excel_output.seek(0)
    return send_file(excel_output, download_name="reporte.xlsx", as_attachment=True)


if __name__ == '__main__':
    app.run(debug=True)
