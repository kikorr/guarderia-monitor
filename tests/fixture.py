"""Ficha sintetica con la MISMA estructura que la real (23-sep-2026) y datos inventados."""
def ficha(ninos, btn=True, p3="1", pide_dni=False):
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
             f'data-p1="P1" data-p2="C1" data-p3="{p3}">Realizar registro</button>') if btn else ""
    return f'''
    <div class="mb-3">Hola PERSONA INVENTADA</div>
    <div class="mb-2 text-center fw-bold"><span id="alu_sel">{len(ninos)}</span> de {len(ninos)} niños/as seleccionados</div>
    <form id="fRegistro" name="fRegistro" method="post" target="ifr_carga">{''.join(cajas)}
    </form>
    <div id="btnsFichaje" class="mb-4 text-center">{boton}
      <div id="divInfo"><ul><li>Por defecto están seleccionados todos los niños</li>
      <li>Si ya se ha realizado algún registro sobre alguno niños del listado, la información aparece debajo del nombre</li></ul></div>
    </div>'''
