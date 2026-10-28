"""
Conecta el minijuego 3 (scenes\\gas.py) con el minijuego 5 con DOS cambios puntuales:
  1) agrega:  from scenes.pipes import PipesScene
  2) cambia:  EndingScene(...)  ->  PipesScene(...)  en la linea que sigue a "ganado"

Conserva la codificacion UTF-8 y los saltos de linea del archivo. Es idempotente.
Para deshacer:  git checkout -- scenes/gas.py
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA = os.path.join(RAIZ, "scenes", "gas.py")

IMPORT_VIEJO = "from scenes.ending import EndingScene"
IMPORT_NUEVO = "from scenes.pipes import PipesScene"
LLAMADA_VIEJA = "self.manager.replace(EndingScene(self.manager, self.state, self.audio))"
LLAMADA_NUEVA = "self.manager.replace(PipesScene(self.manager, self.state, self.audio))"

datos = open(RUTA, "rb").read()
bom = datos.startswith(b"\xef\xbb\xbf")
texto = datos.decode("utf-8-sig")
nl = "\r\n" if "\r\n" in texto else "\n"

if IMPORT_NUEVO in texto and LLAMADA_NUEVA in texto:
    print("gas.py ya estaba conectado. No se cambio nada.")
    sys.exit(0)

if texto.count(IMPORT_VIEJO) != 1 or texto.count(LLAMADA_VIEJA) != 1:
    print("ABORTO: no encontre exactamente una vez las lineas esperadas. No se cambio nada.")
    print("  import:", texto.count(IMPORT_VIEJO), " llamada:", texto.count(LLAMADA_VIEJA))
    sys.exit(1)

texto = texto.replace(IMPORT_VIEJO, IMPORT_VIEJO + nl + IMPORT_NUEVO)
texto = texto.replace(LLAMADA_VIEJA, LLAMADA_NUEVA)
salida = texto.encode("utf-8")
if bom:
    salida = b"\xef\xbb\xbf" + salida
open(RUTA, "wb").write(salida)
print("gas.py actualizado: 2 cambios.")
