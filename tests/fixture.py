"""Ficha sintetica con la MISMA estructura que la real (23-sep-2026) y datos inventados."""
def ficha(ninos, btn=True, p3="1", pide_dni=False, padre="P1"):
    if pide_dni:
        return "<div>Para continuar introduce tu DNI</div><input id='dni' name='dni'>"
    cajas = []
    for n in ninos:
        lis = ""
        if n.get("entrada"):
            lis += f"<ul><li>Entrada: {n['entrada']} - Realizado por: PERSONA INVENTADA - Padre</li></ul>"
        if n.get("salida"):
            lis += f"<ul><li>Salida: {n['salida']} - Realizado por: PERSONA INVENTADA - Padre</li></ul>"
        dis = " disabled hidden" if n.get("disabled") else ""
        cajas.append(f'''
        <div class="cont_hijos mb-4">
            <input type="checkbox" id="chk_{n['id']}" class="chk_alu" name="chk_{n['id']}" value="{n['id']}" {dis} data-ausente="{'1' if n.get('ausente') else '0'}"/>
            <label id="btn_alu_{n['id']}" class="btn_alu" for="chk_{n['id']}" data-alu="{n['id']}">
                <div class="info_alu"><iconify-icon icon="ph:baby-duotone"></iconify-icon><div>NIÑO INVENTADO {n['id']}</div></div>
                <div class="mensaje_alu">{lis}</div>
            </label>
        </div>''')
    boton = (f'<button id="btn_alu" type="button" class="btn btn-primary" data-fn="guardaAccesoAlumno" '
             f'data-p1="{padre}" data-p2="C1" data-p3="{p3}">Realizar registro</button>') if btn else ""
    return f'''
    <div class="mb-3">Hola PERSONA INVENTADA</div>
    <div class="mb-2 text-center fw-bold"><span id="alu_sel">{len(ninos)}</span> de {len(ninos)} niños/as seleccionados</div>
    <form id="fRegistro" name="fRegistro" method="post" target="ifr_carga">{''.join(cajas)}
    </form>
    <div id="btnsFichaje" class="mb-4 text-center">{boton}
      <div id="divInfo"><ul><li>Por defecto están seleccionados todos los niños</li>
      <li>Si ya se ha realizado algún registro sobre alguno niños del listado, la información aparece debajo del nombre</li></ul></div>
    </div>'''


def agenda(entrada=None, salida=None, con_horario=True):
    """Agenda del dia sintetica (misma forma que la real: div.info-item > div.info-titulo > span)."""
    def item(label, valor):
        return (f'<div class="info-item"><div class="info-titulo"><span>{label}</span></div>'
                f'<div class="info-texto"><div>{valor}</div></div></div>')
    partes = [item("Comida", "Todo"), item("Siesta", "12:30 - 14:10"), item("Observaciones Padres", "NIÑO INVENTADO")]
    if con_horario:
        e = entrada or "No disponible"
        s = salida or "No disponible"
        partes.append('<div class="info-item"><div class="info-titulo"><span>Horario</span></div>'
                      f'<div class="info-texto"><div>Entrada: {e}</div><div>Salida: {s}</div></div></div>')
    return "<html><body>" + "".join(partes) + "</body></html>"


def agenda_real(entrada=None, salida=None, con_titulo=True):
    """Agenda con la estructura REAL medida el 24-sep-2026 (datos inventados): pestaña
    div.tabs-alumno > div.tab.cHorario, y div.info-titulo.cHorario seguido de dos div.info-texto.corto
    hermanos, sin div.info-item. con_titulo=False deja solo el texto plano (prueba del respaldo)."""
    e = entrada or "No disponible"
    s = salida or "No disponible"
    tabs = ('<div class="tabs-alumno"><div class="tab cHorario">Horario</div>'
            '<div class="tab cDesayuno">Desayuno</div><div class="tab cComida">Comida</div></div>')
    if con_titulo:
        horario = ('<div class="info-titulo cHorario"><span>Horario</span></div>'
                   f'<div class="info-texto corto">Entrada: {e}</div>'
                   f'<div class="info-texto corto">Salida: {s}</div>')
    else:
        horario = f'<p>Horario</p><p>Entrada: {e}</p><p>Salida: {s}</p>'
    resto = ('<div class="info-titulo cDesayuno"><span>Desayuno</span></div>'
             '<div class="info-texto">Sin datos disponibles</div>'
             '<div class="info-titulo cComida"><span>Comida</span></div>'
             '<div class="info-texto">Entrada: 12:00 (texto de otro apartado, no debe contar)</div>')
    return f'<html><body>{tabs}<div class="contenido-info">{horario}{resto}</div></body></html>'


def respuesta_cookie(id_user="55555", id_centro="9", tipo="1"):
    """compruebaUser.php cuando el servidor ya tiene la cookie del padre (~90 bytes, ids inventados)."""
    return f'<img src="/images/logo2.png" class="d-none" data-onload="tieneCookie({id_user}, \'{id_centro}\', {tipo});" />'


def formulario_dni():
    """compruebaUser.php cuando no hay cookie: el formulario del DNI."""
    return ('<form id="fDni"><label>Introduce tu DNI</label><input type="text" id="dni" name="dni">'
            '<button type="button" data-fn="comprobarPadreValido">Entrar</button></form>')
