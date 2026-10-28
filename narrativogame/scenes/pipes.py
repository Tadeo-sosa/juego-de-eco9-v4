import random
from math import comb

import pygame

from settings import WIDTH, HEIGHT
from engine.scene_manager import Scene
from scenes.ending import EndingScene

"""
MINIJUEGO 5 - Sistema de tuberías y escape de agua.

Como se juega:
    Una habitacion se llena de agua. Conectá la ENTRADA (izquierda) con la SALIDA
    (derecha) girando e intercambiando piezas. El agua que llega a la salida se
    evacua; el agua que se escapa por juntas rotas o extremos abiertos termina en
    la habitacion. Ganas llevando el nivel a 0; perdes si llega a 100.

Matematica (distribucion binomial espacial):
    Evento: "la junta de una pieza MOJADA se fuga durante un pulso" (Bernoulli).
    Posicion: la presion cae a lo largo del recorrido. Segun la distancia d (en
    celdas) desde la entrada, cada pieza mojada cae en una zona:
        Z1: d <= 3 (peso 1.0)   Z2: 4 <= d <= 7 (peso 0.6)   Z3: d >= 8 (peso 0.3)
    Probabilidad de fuga de una pieza del grupo (zona z, estado e):
        p = min(0.9, p_estado * (1 + 2 * Pres(t) * w_z))
        p_sana = 0.04, p_oxidada = 0.20, Pres(t) sube de 0.2 a 1.0 en 60 s.
    Dentro de un grupo hay n piezas con la misma p, asumidas independientes:
        K_grupo ~ Binomial(n, p)
    El total K es la suma de binomiales independientes (Poisson-binomial). Se
    calcula su ley exacta por convolucion. El pulso sortea las piezas con esas
    mismas p, asi que lo que muestra el panel es la ley real del juego.
"""

# ---------------- constantes ajustables ----------------
COLS, ROWS = 6, 5
CELDA = 72
TX, TY = 40, 110                 # esquina superior izquierda del tablero

Q = 4                            # unidades de agua que entran por pulso
NIVEL_INICIAL = 40
NIVEL_MAX = 100
PULSO = 2.5                      # segundos entre pulsos
GRACIA = 15.0                    # segundos antes del primer pulso (tiempo para armar el recorrido)
DRENAJE = 5.0                    # cuanta agua de la habitacion se evacua por D que llega

P_BASE = {False: 0.04, True: 0.20}    # p de fuga: pieza sana / oxidada
W_ZONA = (1.0, 0.6, 0.3)              # peso de presion por zona
ZONA_LIM = (3, 7)                     # d<=3 -> Z1, d<=7 -> Z2, resto Z3
PRES_INI, PRES_TIEMPO = 0.2, 60.0     # Pres(t) = 0.2 -> 1.0 en 60 s
P_MAX = 0.9

N_ESCOMBROS = 3
N_INTERCAMBIOS = 3
FALLOS_PARA_SALTAR = 2           # tras estos fallos se permite abandonar con ESC

# ---------------- piezas ----------------
NORTE, ESTE, SUR, OESTE = 0, 1, 2, 3
DELTA = ((-1, 0), (0, 1), (1, 0), (0, -1))          # (fila, columna) por direccion
BASE = {
    "recta": (NORTE, SUR),
    "codo": (NORTE, ESTE),
    "te": (OESTE, NORTE, ESTE),
    "cruz": (NORTE, ESTE, SUR, OESTE),
}


class Celda:
    """tipo: 'vacio', 'escombro', 'recta', 'codo', 'te' o 'cruz'."""
    __slots__ = ("tipo", "rot", "oxidada")

    def __init__(self, tipo="vacio", rot=0, oxidada=False):
        self.tipo = tipo
        self.rot = rot
        self.oxidada = oxidada

    @property
    def es_tubo(self):
        return self.tipo in BASE

    def aperturas(self):
        if not self.es_tubo:
            return frozenset()
        return frozenset((d + self.rot) % 4 for d in BASE[self.tipo])

    def copia(self):
        return Celda(self.tipo, self.rot, self.oxidada)


# ---------------- conexiones reales ----------------
def evaluar(grid, ent, sal):
    """
    Recorre el agua desde la entrada (BFS).
    Devuelve:
        mojadas:   {(fila, col): distancia desde la entrada}
        conectado: True si el agua llega a la salida
        extremos:  lista de ((fila, col), direccion, motivo) donde el agua se derrama
                   motivo: 'borde', 'vacio', 'obstruccion' o 'sin_union'
    """
    mojadas, extremos, conectado = {}, [], False
    inicio = grid[ent][0]
    if inicio.es_tubo and OESTE in inicio.aperturas():
        mojadas[(ent, 0)] = 0
        cola = [(ent, 0)]
        while cola:
            r, c = cola.pop(0)
            dist = mojadas[(r, c)]
            for d in sorted(grid[r][c].aperturas()):
                if (r, c) == (ent, 0) and d == OESTE:
                    continue                        # es la entrada de agua
                if (r, c) == (sal, COLS - 1) and d == ESTE:
                    conectado = True                # es la salida
                    continue
                nr, nc = r + DELTA[d][0], c + DELTA[d][1]
                if not (0 <= nr < ROWS and 0 <= nc < COLS):
                    extremos.append(((r, c), d, "borde"))
                    continue
                vecina = grid[nr][nc]
                if vecina.tipo == "escombro":
                    extremos.append(((r, c), d, "obstruccion"))
                elif not vecina.es_tubo:
                    extremos.append(((r, c), d, "vacio"))
                elif (d + 2) % 4 in vecina.aperturas():
                    if (nr, nc) not in mojadas:
                        mojadas[(nr, nc)] = dist + 1
                        cola.append((nr, nc))
                else:
                    extremos.append(((r, c), d, "sin_union"))
    return {"mojadas": mojadas, "conectado": conectado, "extremos": extremos}


# ---------------- modelo probabilistico ----------------
def zona_de(dist):
    if dist <= ZONA_LIM[0]:
        return 0
    return 1 if dist <= ZONA_LIM[1] else 2


def presion(t):
    return min(1.0, PRES_INI + (1.0 - PRES_INI) * t / PRES_TIEMPO)


def prob_fuga(zona, oxidada, pres):
    return min(P_MAX, P_BASE[oxidada] * (1 + 2 * pres * W_ZONA[zona]))


def grupos_de(grid, mojadas):
    """{(zona, oxidada): n piezas mojadas}"""
    grupos = {}
    for (r, c), dist in mojadas.items():
        clave = (zona_de(dist), grid[r][c].oxidada)
        grupos[clave] = grupos.get(clave, 0) + 1
    return grupos


def pmf_fugas(grupos, pres):
    """Ley exacta de K = suma de Binomial(n_g, p_g): convolucion de binomiales."""
    pmf = [1.0]
    for (zona, ox), n in grupos.items():
        p = prob_fuga(zona, ox, pres)
        b = [comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
        nuevo = [0.0] * (len(pmf) + n)
        for i, a in enumerate(pmf):
            for j, x in enumerate(b):
                nuevo[i + j] += a * x
        pmf = nuevo
    return pmf


def esperanza_fugas(grupos, pres):
    return sum(n * prob_fuga(z, ox, pres) for (z, ox), n in grupos.items())


# ---------------- generacion de niveles ----------------
def camino_aleatorio(rng, ent, sal):
    destino = (sal, COLS - 1)
    visitado = {(ent, 0)}
    camino = [(ent, 0)]
    presupuesto = [3000]

    def dfs(r, c):
        if (r, c) == destino:
            return True
        presupuesto[0] -= 1
        if presupuesto[0] <= 0:
            return False
        dirs = [NORTE, ESTE, SUR, OESTE]
        rng.shuffle(dirs)
        if rng.random() < 0.35:
            dirs.remove(ESTE)
            dirs.insert(0, ESTE)
        for d in dirs:
            nr, nc = r + DELTA[d][0], c + DELTA[d][1]
            if 0 <= nr < ROWS and 0 <= nc < COLS and (nr, nc) not in visitado:
                visitado.add((nr, nc))
                camino.append((nr, nc))
                if dfs(nr, nc):
                    return True
                camino.pop()
                visitado.discard((nr, nc))
        return False

    return camino if dfs(ent, 0) else None


def _direccion(a, b):
    dr, dc = b[0] - a[0], b[1] - a[1]
    return DELTA.index((dr, dc))


def generar_nivel(rng):
    """
    Devuelve (grid_resuelto, entrada, salida, camino). La solucion existe por
    construccion y se verifica con la misma funcion evaluar() que usa el juego.
    """
    while True:
        camino, ent, sal = None, 2, 2
        for intento in range(400):
            ent, sal = rng.randrange(ROWS), rng.randrange(ROWS)
            c = camino_aleatorio(rng, ent, sal)
            if c and (9 <= len(c) <= 16 or intento >= 300):
                camino = c
                break
        if camino is None:
            ent = sal = 2
            camino = [(2, c) for c in range(COLS)]

        grid = [[Celda() for _ in range(COLS)] for _ in range(ROWS)]
        for i, (r, c) in enumerate(camino):
            ant = OESTE if i == 0 else _direccion((r, c), camino[i - 1])
            sig = ESTE if i == len(camino) - 1 else _direccion((r, c), camino[i + 1])
            tipo = "recta" if (ant + 2) % 4 == sig else "codo"
            cel = Celda(tipo)
            for rot in range(4):
                cel.rot = rot
                if cel.aperturas() == frozenset((ant, sig)):
                    break
            grid[r][c] = cel

        for i in rng.sample(range(len(camino)), rng.choice((2, 3))):
            r, c = camino[i]
            grid[r][c].oxidada = True

        fuera = [(r, c) for r in range(ROWS) for c in range(COLS) if (r, c) not in set(camino)]
        escombros = rng.sample(fuera, N_ESCOMBROS)
        for r, c in escombros:
            grid[r][c] = Celda("escombro")
        libres = [p for p in fuera if p not in escombros]
        for r, c in libres:
            tipo = rng.choices(["vacio", "recta", "codo", "te", "cruz"],
                               weights=[30, 25, 25, 12, 8])[0]
            grid[r][c] = Celda(tipo, rng.randrange(4), tipo != "vacio" and rng.random() < 0.15)

        # Para que mover piezas tenga sentido: por cada tipo oxidado en el camino
        # existe al menos un repuesto sano del mismo tipo fuera del camino.
        for r, c in camino:
            if grid[r][c].oxidada:
                tipo = grid[r][c].tipo
                if not any(grid[a][b].tipo == tipo and not grid[a][b].oxidada for a, b in libres):
                    a, b = rng.choice(libres)
                    grid[a][b] = Celda(tipo, rng.randrange(4), False)

        ev = evaluar(grid, ent, sal)
        if ev["conectado"] and not ev["extremos"]:
            return grid, ent, sal, camino


def desordenar(grid, camino, ent, sal, rng):
    """Gira todas las piezas y hace unos intercambios. Nunca devuelve un nivel ya resuelto."""
    extremos = {(ent, 0), (sal, COLS - 1)}      # la pieza de la entrada y de la salida no se desplazan
    movibles = [(r, c) for r in range(ROWS) for c in range(COLS)
                if grid[r][c].tipo != "escombro" and (r, c) not in extremos]
    intercambiables = [p for p in camino if p not in extremos]
    g = grid
    for _ in range(30):
        g = [[cel.copia() for cel in fila] for fila in grid]
        for fila in g:
            for cel in fila:
                if cel.es_tubo:
                    cel.rot = rng.randrange(4)
        for _ in range(N_INTERCAMBIOS):
            a, b = rng.choice(intercambiables), rng.choice(movibles)
            if a != b:
                g[a[0]][a[1]], g[b[0]][b[1]] = g[b[0]][b[1]], g[a[0]][a[1]]
        ev = evaluar(g, ent, sal)
        if not ev["conectado"] or ev["extremos"]:
            return g
    return g


def nuevo_nivel(rng):
    grid, ent, sal, camino = generar_nivel(rng)
    return desordenar(grid, camino, ent, sal, rng), ent, sal


# ---------------- escena ----------------
class PipesScene(Scene):
    """
    MINIJUEGO 5 - Tuberias y escape de agua.
    siguiente: funcion opcional (manager, state, audio) -> Scene a la que se pasa al
    ganar. Si es None, va a EndingScene.
    """

    def __init__(self, manager, state, audio, siguiente=None, rng=None):
        super().__init__(manager)
        self.state = state
        self.audio = audio
        self.siguiente = siguiente
        self.rng = rng or random.Random()
        self.f_titulo = pygame.font.Font(None, 38)
        self.f = pygame.font.Font(None, 28)
        self.f_peq = pygame.font.Font(None, 22)
        self.input_cooldown = 0.0
        self.intentos = 0
        self.fugas_totales = 0
        self.nivel_max_global = 0.0
        self.reiniciar(intro=True)

    def on_enter(self):
        self.input_cooldown = 0.4

    def reiniciar(self, intro=False):
        self.fase = "intro" if intro else "jugando"
        self.grid, self.ent, self.sal = nuevo_nivel(self.rng)
        self.cursor = (self.ent, 0)
        self.sostenida = None
        self.nivel = float(NIVEL_INICIAL)
        self.nivel_vista = float(NIVEL_INICIAL)
        self.nivel_max = float(NIVEL_INICIAL)
        self.t_juego = 0.0
        self.acum_pulso = 0.0
        self.pulsos = 0
        self.fugas_obs = 0
        self.fugas_esp = 0.0
        self.destellos = {}
        self.mensaje = "Girá piezas, intercambialas y conectá la entrada con la salida."
        self.color_msg = (235, 235, 235)
        self.motivo = ""

    @property
    def finalizado(self):
        return self.fase in ("ganado", "perdido")

    # ---------------- acciones del jugador ----------------
    def mover_cursor(self, dr, dc):
        r, c = self.cursor
        self.cursor = (max(0, min(ROWS - 1, r + dr)), max(0, min(COLS - 1, c + dc)))

    def rotar(self, pos, delta):
        if self.fase != "jugando":
            return
        cel = self.grid[pos[0]][pos[1]]
        if not cel.es_tubo:
            self.mensaje, self.color_msg = "Ahí no hay una tubería para girar.", (240, 200, 90)
            return
        cel.rot = (cel.rot + delta) % 4
        if self.audio:
            self.audio.play_click()

    def agarrar_o_soltar(self, pos):
        if self.fase != "jugando":
            return
        r, c = pos
        cel = self.grid[r][c]
        if self.sostenida is None:
            if cel.es_tubo:
                self.sostenida = pos
                self.mensaje, self.color_msg = "Pieza agarrada: elegí otra celda y apretá ESPACIO.", (130, 220, 150)
            elif cel.tipo == "escombro":
                self.mensaje, self.color_msg = "Los escombros no se pueden mover.", (240, 130, 110)
            else:
                self.mensaje, self.color_msg = "No hay pieza para agarrar ahí.", (240, 200, 90)
        elif pos == self.sostenida:
            self.sostenida = None
            self.mensaje, self.color_msg = "Soltaste la pieza en su lugar.", (235, 235, 235)
        elif cel.tipo == "escombro":
            self.mensaje, self.color_msg = "No podés dejar una pieza sobre los escombros.", (240, 130, 110)
        else:
            a = self.sostenida
            self.grid[a[0]][a[1]], self.grid[r][c] = self.grid[r][c], self.grid[a[0]][a[1]]
            self.sostenida = None
            self.mensaje, self.color_msg = "Intercambiaste las piezas.", (235, 235, 235)
            if self.audio:
                self.audio.play_click()

    def celda_en(self, pos):
        x, y = pos[0] - TX, pos[1] - TY
        if 0 <= x < COLS * CELDA and 0 <= y < ROWS * CELDA:
            return (y // CELDA, x // CELDA)
        return None

    def empezar(self):
        self.fase = "jugando"

    def continuar(self):
        if self.siguiente:
            escena = self.siguiente(self.manager, self.state, self.audio)
        else:
            escena = EndingScene(self.manager, self.state, self.audio)
        self.manager.replace(escena)

    # ---------------- pulso de agua ----------------
    def pulso(self):
        ev = evaluar(self.grid, self.ent, self.sal)
        pres = presion(self.t_juego)
        grupos = grupos_de(self.grid, ev["mojadas"])
        fugas = []
        for (r, c), dist in ev["mojadas"].items():
            p = prob_fuga(zona_de(dist), self.grid[r][c].oxidada, pres)
            if self.rng.random() < p:
                fugas.append((r, c))
        k, ext = len(fugas), len(ev["extremos"])
        self.fugas_esp += esperanza_fugas(grupos, pres)
        self.fugas_obs += k
        llega = max(0, Q - k - ext) if ev["conectado"] else 0
        delta = (Q - llega) - DRENAJE * llega / Q
        self.nivel = max(0.0, min(float(NIVEL_MAX), self.nivel + delta))
        self.nivel_max = max(self.nivel_max, self.nivel)
        self.pulsos += 1
        for pos in fugas:
            self.destellos[pos] = 0.6
        self.mensaje = f"Pulso {self.pulsos}: salieron {llega} de {Q}  ·  {k} fugas  ·  {ext} extremos abiertos"
        self.color_msg = (130, 220, 150) if delta < 0 else (240, 140, 120)
        if self.nivel >= NIVEL_MAX:
            self.motivo = "La habitación se inundó."
            self.terminar(False)
        elif self.nivel <= 0:
            self.motivo = "Evacuaste toda el agua de la habitación."
            self.terminar(True)

    def terminar(self, gano):
        self.fase = "ganado" if gano else "perdido"
        self.intentos += 1
        self.fugas_totales += self.fugas_obs
        self.nivel_max_global = max(self.nivel_max_global, self.nivel_max)
        self.sostenida = None
        st = self.state
        st.stats["tuberias_intentos"] = self.intentos
        st.stats["tuberias_fugas"] = self.fugas_totales
        st.stats["tuberias_nivel_max"] = round(self.nivel_max_global, 1)
        st.set_flag("tuberias_superadas", gano)
        if gano:
            st.add("curiosidad", 1)

    # ---------------- eventos ----------------
    def handle_event(self, event):
        if self.input_cooldown > 0:
            return
        if event.type == pygame.KEYDOWN:
            k = event.key
            if self.fase == "intro" and k in (pygame.K_SPACE, pygame.K_RETURN):
                self.empezar()
            elif self.fase == "perdido":
                if k == pygame.K_r:
                    self.reiniciar()
                elif k == pygame.K_ESCAPE and self.intentos >= FALLOS_PARA_SALTAR:
                    self.continuar()
            elif self.fase == "ganado" and k in (pygame.K_SPACE, pygame.K_RETURN):
                self.continuar()
            elif self.fase == "jugando":
                if k in (pygame.K_UP, pygame.K_w):
                    self.mover_cursor(-1, 0)
                elif k in (pygame.K_DOWN, pygame.K_s):
                    self.mover_cursor(1, 0)
                elif k in (pygame.K_LEFT, pygame.K_a):
                    self.mover_cursor(0, -1)
                elif k in (pygame.K_RIGHT, pygame.K_d):
                    self.mover_cursor(0, 1)
                elif k == pygame.K_q:
                    self.rotar(self.cursor, -1)
                elif k == pygame.K_e:
                    self.rotar(self.cursor, 1)
                elif k in (pygame.K_SPACE, pygame.K_RETURN):
                    self.agarrar_o_soltar(self.cursor)
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if self.fase == "intro" and event.button == 1:
                self.empezar()
            elif self.fase == "jugando":
                pos = self.celda_en(event.pos)
                if pos is not None:
                    self.cursor = pos
                    if event.button == 1:
                        self.rotar(pos, 1)
                    elif event.button == 3:
                        self.agarrar_o_soltar(pos)

    def update(self, dt):
        if self.input_cooldown > 0:
            self.input_cooldown -= dt
        self.nivel_vista += max(-30 * dt, min(30 * dt, self.nivel - self.nivel_vista))
        for pos in list(self.destellos):
            self.destellos[pos] -= dt
            if self.destellos[pos] <= 0:
                del self.destellos[pos]
        if self.fase == "jugando":
            self.t_juego += dt
            if self.t_juego >= GRACIA:
                self.acum_pulso += dt
                while self.acum_pulso >= PULSO and self.fase == "jugando":
                    self.acum_pulso -= PULSO
                    self.pulso()

    # ---------------- dibujo ----------------
    def texto(self, surf, txt, pos, fuente=None, color=(235, 235, 235), centro=False):
        img = (fuente or self.f).render(txt, True, color)
        r = img.get_rect(center=pos) if centro else img.get_rect(topleft=pos)
        surf.blit(img, r)

    def rect_celda(self, r, c):
        return pygame.Rect(TX + c * CELDA, TY + r * CELDA, CELDA, CELDA)

    def dibujar_tubo(self, s, cel, rect, mojada):
        cx, cy = rect.center
        if cel.oxidada:
            col = (110, 175, 215) if mojada else (176, 122, 82)
        else:
            col = (90, 170, 245) if mojada else (140, 148, 170)
        for d in cel.aperturas():
            dr, dc = DELTA[d]
            pygame.draw.line(s, col, (cx, cy), (cx + dc * (CELDA // 2), cy + dr * (CELDA // 2)), 14)
        pygame.draw.circle(s, col, (cx, cy), 9)
        if cel.oxidada:
            for ox, oy in ((-6, -4), (5, 3), (-2, 7)):
                pygame.draw.circle(s, (205, 105, 45), (cx + ox, cy + oy), 3)

    def dibujar_escombro(self, s, rect):
        pygame.draw.rect(s, (96, 92, 100), rect.inflate(-18, -26), border_radius=6)
        pygame.draw.rect(s, (120, 114, 122), (rect.x + 14, rect.y + 16, 22, 18), border_radius=4)
        pygame.draw.line(s, (210, 90, 90), (rect.x + 18, rect.y + 18), (rect.right - 18, rect.bottom - 18), 4)
        pygame.draw.line(s, (210, 90, 90), (rect.right - 18, rect.y + 18), (rect.x + 18, rect.bottom - 18), 4)

    def dibujar_tablero(self, s, ev):
        pygame.draw.rect(s, (14, 17, 26), (TX - 4, TY - 4, COLS * CELDA + 8, ROWS * CELDA + 8), border_radius=6)
        for r in range(ROWS):
            for c in range(COLS):
                rect = self.rect_celda(r, c)
                cel = self.grid[r][c]
                pygame.draw.rect(s, (30, 36, 52), rect)
                pygame.draw.rect(s, (52, 60, 82), rect, 1)
                if cel.tipo == "escombro":
                    self.dibujar_escombro(s, rect)
                elif cel.es_tubo:
                    self.dibujar_tubo(s, cel, rect, (r, c) in ev["mojadas"])
                if (r, c) in self.destellos:
                    pygame.draw.circle(s, (255, 120, 100), rect.center, 20, 3)
        for (r, c), d, _ in ev["extremos"]:
            cx, cy = self.rect_celda(r, c).center
            dr, dc = DELTA[d]
            pygame.draw.circle(s, (240, 90, 90), (cx + dc * (CELDA // 2), cy + dr * (CELDA // 2)), 6)
        if self.sostenida:
            pygame.draw.rect(s, (110, 220, 140), self.rect_celda(*self.sostenida), 3)
        pygame.draw.rect(s, (250, 220, 90), self.rect_celda(*self.cursor).inflate(-4, -4), 3)
        # entrada y salida
        y = TY + self.ent * CELDA + CELDA // 2
        pygame.draw.polygon(s, (90, 170, 245), [(TX - 26, y - 12), (TX - 26, y + 12), (TX - 6, y)])
        self.texto(s, "ENT", (TX - 17, y - 24), self.f_peq, (90, 170, 245), centro=True)
        y = TY + self.sal * CELDA + CELDA // 2
        xs = TX + COLS * CELDA
        col = (110, 220, 140) if ev["conectado"] else (120, 126, 145)
        pygame.draw.polygon(s, col, [(xs + 4, y - 12), (xs + 4, y + 12), (xs + 24, y)])
        self.texto(s, "SAL", (xs + 15, y - 24), self.f_peq, col, centro=True)

    def dibujar_nivel(self, s):
        x, w, h = 520, 44, ROWS * CELDA
        pygame.draw.rect(s, (14, 17, 26), (x, TY, w, h))
        alto = int(self.nivel_vista / NIVEL_MAX * h)
        pygame.draw.rect(s, (70, 140, 230), (x, TY + h - alto, w, alto))
        pygame.draw.rect(s, (200, 70, 70), (x, TY, w, int(h * 0.2)), 2)
        pygame.draw.rect(s, (230, 230, 240), (x, TY, w, h), 2)
        self.texto(s, f"AGUA {int(round(self.nivel_vista))}", (x + w // 2, TY - 14), self.f_peq, centro=True)

    def estado_conexion(self, ev):
        ext = len(ev["extremos"])
        if ev["conectado"] and ext == 0:
            return "Conexión completa, sin derrames", (130, 220, 150)
        if ev["conectado"]:
            return f"Conectado, pero {ext} extremos abiertos", (240, 200, 90)
        if not ev["mojadas"]:
            return "El agua no entra: falta pieza en la entrada", (240, 130, 110)
        if any(m == "obstruccion" for _, _, m in ev["extremos"]):
            return "Recorrido OBSTRUIDO por escombros", (240, 130, 110)
        return "Recorrido incompleto: el agua se derrama", (240, 130, 110)

    def dibujar_panel(self, s, ev):
        x = 590
        pres = presion(self.t_juego)
        grupos = grupos_de(self.grid, ev["mojadas"])
        pmf = pmf_fugas(grupos, pres)
        self.texto(s, "MODELO DE FUGAS", (x, TY), self.f, (150, 200, 255))
        self.texto(s, f"Presión de línea: {pres * 100:.0f}%", (x, TY + 28), self.f_peq)
        pygame.draw.rect(s, (14, 17, 26), (x, TY + 50, 330, 10))
        pygame.draw.rect(s, (int(80 + 170 * pres), int(200 - 120 * pres), 90), (x, TY + 50, int(330 * pres), 10))
        self.texto(s, f"Piezas mojadas: {len(ev['mojadas'])}  ·  Extremos abiertos: {len(ev['extremos'])}",
                   (x, TY + 70), self.f_peq)
        self.texto(s, "p de fuga por pieza (zona, estado):", (x, TY + 94), self.f_peq, (190, 195, 210))
        y = TY + 116
        for (z, ox), n in sorted(grupos.items()):
            p = prob_fuga(z, ox, pres)
            self.texto(s, f"Z{z + 1} {'oxidada' if ox else 'sana'}: n={n}  p={p:.2f}", (x + 10, y), self.f_peq,
                       (205, 130, 80) if ox else (235, 235, 235))
            y += 22
        y = TY + 252
        if grupos:
            self.texto(s, f"E[fugas por pulso] = {esperanza_fugas(grupos, pres):.2f}", (x, y), self.f_peq)
            self.texto(s, f"P(0 fugas) = {pmf[0]:.0%}   P(2 o más) = {max(0.0, 1 - pmf[0] - (pmf[1] if len(pmf) > 1 else 0)):.0%}",
                       (x, y + 22), self.f_peq)
        else:
            self.texto(s, "Sin piezas mojadas: no hay fugas que calcular.", (x, y), self.f_peq)
        texto, col = self.estado_conexion(ev)
        self.texto(s, texto, (x, TY + 306), self.f_peq, col)
        if self.t_juego < GRACIA and self.fase == "jugando":
            sig = f"El agua llega en {max(0.0, GRACIA - self.t_juego):.0f} s"
        else:
            sig = f"Próximo pulso en {max(0.0, PULSO - self.acum_pulso):.1f} s"
        self.texto(s, sig, (x, TY + 330), self.f_peq, (190, 195, 210))
        if ev["conectado"]:
            esp = esperanza_fugas(grupos, pres)
            llega = max(0.0, Q - esp - len(ev["extremos"]))
            delta = (Q - llega) - DRENAJE * llega / Q
            tend, col_t = ("El nivel del agua BAJA", (130, 220, 150)) if delta < 0 else \
                          ("El nivel NO baja: demasiadas fugas o extremos abiertos", (240, 130, 110))
        else:
            tend, col_t = "El nivel del agua SUBE: falta conectar", (240, 130, 110)
        self.texto(s, tend, (x, TY + 354), self.f_peq, col_t)

    def dibujar_cartel(self, s, titulo, color, lineas, pie):
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((10, 12, 20, 200))
        s.blit(vel, (0, 0))
        caja = pygame.Rect(110, 100, WIDTH - 220, 330)
        pygame.draw.rect(s, (26, 32, 48), caja, border_radius=16)
        pygame.draw.rect(s, color, caja, 3, border_radius=16)
        self.texto(s, titulo, (WIDTH // 2, caja.y + 40), self.f_titulo, color, centro=True)
        y = caja.y + 90
        for linea in lineas:
            self.texto(s, linea, (WIDTH // 2, y), self.f_peq, centro=True)
            y += 28
        self.texto(s, pie, (WIDTH // 2, caja.bottom - 34), self.f, (250, 220, 90), centro=True)

    def draw(self):
        s = self.manager.screen
        s.fill((20, 24, 36))
        ev = evaluar(self.grid, self.ent, self.sal)
        self.texto(s, "MINIJUEGO 5 · TUBERÍAS Y ESCAPE DE AGUA", (40, 16), self.f_titulo)
        self.texto(s, self.mensaje, (40, 60), self.f, self.color_msg)
        self.dibujar_tablero(s, ev)
        self.dibujar_nivel(s)
        self.dibujar_panel(s, ev)
        self.texto(s, "Flechas/WASD: cursor  ·  Q/E: girar  ·  ESPACIO: agarrar/soltar pieza",
                   (40, 486), self.f_peq, (190, 195, 210))
        self.texto(s, "Mouse: clic izq. gira  ·  clic der. agarra/suelta  ·  R: reintentar al perder",
                   (40, 508), self.f_peq, (190, 195, 210))

        if self.fase == "intro":
            self.dibujar_cartel(s, "UNA HABITACIÓN SE INUNDA", (90, 170, 245), [
                "Conectá la ENTRADA (izquierda) con la SALIDA (derecha).",
                "Girá piezas (Q/E) e intercambialas de lugar (ESPACIO).",
                "Los escombros bloquean el paso y las piezas oxidadas se fugan más.",
                "Cerca de la entrada la presión es mayor: ahí las fugas son más probables.",
                "Ganás llevando el agua de la habitación a 0. Perdés si llega a 100.",
            ], "ESPACIO o clic para empezar")
        elif self.fase in ("ganado", "perdido"):
            gano = self.fase == "ganado"
            lineas = [
                self.motivo,
                f"Fugas observadas: {self.fugas_obs}  ·  esperadas por el modelo: {self.fugas_esp:.1f}",
                f"Pulsos: {self.pulsos}  ·  Nivel máximo de agua: {self.nivel_max:.0f}",
            ]
            if not gano:
                lineas.append("Consejo: alejá las piezas oxidadas de la entrada o cambialas por sanas.")
            pie = "ESPACIO o ENTER para continuar" if gano else "R para reintentar"
            if not gano and self.intentos >= FALLOS_PARA_SALTAR:
                pie += "  ·  ESC para seguir sin salvarla"
            self.dibujar_cartel(s, "HABITACIÓN A SALVO" if gano else "HABITACIÓN INUNDADA",
                                (110, 220, 140) if gano else (240, 110, 100), lineas, pie)