import random
import pygame

from settings import WIDTH, HEIGHT
from engine.scene_manager import Scene
from scenes.ending import EndingScene


class ValvulasScene(Scene):
    """
    MINIJUEGO 3 - Control de válvulas y presión de gas.

    Cómo se juega:
        Una planta de gas tiene una presión (la aguja). Tenés que mantenerla en la
        zona VERDE durante 8 turnos. Hay 3 válvulas, que podés abrir o cerrar:
            - ENTRADA   -> tiende a SUBIR la presión
            - SALIDA    -> tiende a BAJAR la presión
            - REGULADOR -> tiende a MANTENERLA igual
        Cada turno hay un CLIMA distinto (se ve arriba) que empuja la presión.
        Además, una válvula que dejás abierta se RECALIENTA y funciona peor:
        hay que ir cambiando de válvulas. Si la aguja llega a la zona ROJA, explota.

    Matemática (probabilidad condicional):
        Lo que pase en cada turno depende de lo que decidiste:
            P(la presión sube | ENTRADA abierta) no es igual que
            P(la presión sube | ENTRADA cerrada).
        El panel muestra esas probabilidades antes de cada turno y, al final, el
        juego calcula con TUS datos:  P(A | B) = P(A y B) / P(B).
    """

    TOTAL_TURNOS = 10
    PRESION_INICIAL = 50
    SALTO = 13
    ROJO_MIN, ROJO_MAX = 10, 90          # fuera de este rango: explota
    VERDE_MIN, VERDE_MAX = 30, 70        # zona segura

    # Clima de cada turno: cambia las probabilidades de partida
    CLIMAS = {
        "calma":    {"nombre": "CALMA", "texto": "sin presión extra",
                     "p": {"sube": 0.30, "igual": 0.40, "baja": 0.30}, "color": (130, 220, 150)},
        "entrada":  {"nombre": "GAS ENTRANDO", "texto": "tiende a SUBIR",
                     "p": {"sube": 0.55, "igual": 0.30, "baja": 0.15}, "color": (240, 130, 110)},
        "demanda":  {"nombre": "MUCHA DEMANDA", "texto": "tiende a BAJAR",
                     "p": {"sube": 0.15, "igual": 0.30, "baja": 0.55}, "color": (120, 170, 245)},
        "tormenta": {"nombre": "TORMENTA", "texto": "inestable: sube o baja",
                     "p": {"sube": 0.40, "igual": 0.20, "baja": 0.40}, "color": (240, 200, 90)},
    }
    PESOS_CLIMA = [("calma", 0.25), ("entrada", 0.25), ("demanda", 0.25), ("tormenta", 0.25)]
    DESGASTE = 0.35        # cuánto pierde de eficacia una válvula por cada turno seguido abierta
    # efecto de cada válvula ABIERTA sobre cada evento
    EFECTOS = {
        "entrada":   {"sube": +0.30, "igual": -0.10, "baja": -0.20},
        "salida":    {"sube": -0.20, "igual": -0.10, "baja": +0.30},
        "regulador": {"sube": -0.15, "igual": +0.30, "baja": -0.15},
    }
    VALVULAS = [
        {"id": "entrada", "nombre": "ENTRADA", "evento": "sube",
         "desc": "Mete gas: tiende a SUBIR", "color": (230, 90, 90)},
        {"id": "salida", "nombre": "SALIDA", "evento": "baja",
         "desc": "Saca gas: tiende a BAJAR", "color": (90, 150, 240)},
        {"id": "regulador", "nombre": "REGULADOR", "evento": "igual",
         "desc": "Estabiliza: tiende a MANTENER", "color": (100, 210, 130)},
    ]
    NOMBRE_EVENTO = {"sube": "SUBA", "igual": "SE MANTENGA", "baja": "BAJE"}

    # ---------------- matemática ----------------
    @classmethod
    def eficacia(cls, racha):
        """Una válvula que lleva 'racha' turnos abierta rinde menos (se recalienta)."""
        return max(0.2, 1 - cls.DESGASTE * racha)

    @classmethod
    def probabilidades(cls, abiertas, rachas, clima):
        """P(evento | clima, válvulas abiertas). Suma 1."""
        p = dict(cls.CLIMAS[clima]["p"])
        for v in abiertas:
            ef = cls.eficacia(rachas[v])
            for ev, delta in cls.EFECTOS[v].items():
                p[ev] += delta * ef
        p = {ev: max(0.05, x) for ev, x in p.items()}
        total = sum(p.values())
        return {ev: x / total for ev, x in p.items()}

    # ---------------- inicio ----------------
    def __init__(self, manager, state, audio):
        super().__init__(manager)
        self.state = state
        self.audio = audio
        self.f_titulo = pygame.font.Font(None, 46)
        self.f = pygame.font.Font(None, 28)
        self.f_peq = pygame.font.Font(None, 22)
        self.input_cooldown = 0.0
        self.reiniciar(intro=True)

    def on_enter(self):
        self.input_cooldown = 0.4

    def reiniciar(self, intro=False):
        self.fase = "intro" if intro else "jugando"
        self.presion = self.PRESION_INICIAL
        self.presion_vista = float(self.PRESION_INICIAL)
        self.turno = 1
        self.abiertas = {"entrada": False, "salida": False, "regulador": False}
        self.rachas = {"entrada": 0, "salida": 0, "regulador": 0}   # turnos seguidos abiertas
        self.historial = []     # cada turno: (válvulas abiertas, evento, clima)
        self.clima = self.sortear_clima()
        self.mensaje = "Elegí qué válvulas abrir y apretá ESPACIO."
        self.color_msg = (235, 235, 235)
        self.motivo = ""

    def sortear_clima(self):
        r, acum = random.random(), 0.0
        for nombre, peso in self.PESOS_CLIMA:
            acum += peso
            if r < acum:
                return nombre
        return "calma"

    @property
    def finalizado(self):
        return self.fase in ("ganado", "perdido")

    # ---------------- lógica ----------------
    def lista_abiertas(self):
        return [k for k, v in self.abiertas.items() if v]

    def alternar(self, i):
        if self.fase != "jugando":
            return
        vid = self.VALVULAS[i]["id"]
        self.abiertas[vid] = not self.abiertas[vid]
        if self.audio:
            self.audio.play_click()

    def zona(self, p):
        if p < self.ROJO_MIN or p > self.ROJO_MAX:
            return "rojo"
        if self.VERDE_MIN <= p <= self.VERDE_MAX:
            return "verde"
        return "amarillo"

    def avanzar(self):
        if self.fase != "jugando":
            return
        abiertas = self.lista_abiertas()
        pr = self.probabilidades(abiertas, self.rachas, self.clima)
        r, acum, evento = random.random(), 0.0, "igual"
        for ev in ("sube", "igual", "baja"):
            acum += pr[ev]
            if r < acum:
                evento = ev
                break
        self.historial.append((tuple(abiertas), evento, self.clima))
        for vid in self.rachas:        # recalentamiento / enfriado
            if vid in abiertas:
                self.rachas[vid] += 1
            else:
                self.rachas[vid] = max(0, self.rachas[vid] - 1)
        if evento == "sube":
            self.presion += self.SALTO
            self.mensaje = f"Turno {self.turno}: la presión SUBIÓ."
            self.color_msg = (240, 140, 120)
        elif evento == "baja":
            self.presion -= self.SALTO
            self.mensaje = f"Turno {self.turno}: la presión BAJÓ."
            self.color_msg = (130, 180, 245)
        else:
            self.mensaje = f"Turno {self.turno}: la presión SE MANTUVO."
            self.color_msg = (130, 220, 150)
        self.presion = max(0, min(100, self.presion))

        if self.zona(self.presion) == "rojo":
            self.motivo = ("¡Presión demasiado ALTA: el sistema explotó!" if self.presion > self.ROJO_MAX
                           else "Presión demasiado BAJA: el sistema se apagó.")
            self.terminar(False)
        elif self.turno >= self.TOTAL_TURNOS:
            if self.zona(self.presion) == "verde":
                self.motivo = "¡Aguantaste los 10 turnos con la presión segura!"
                self.terminar(True)
            else:
                self.motivo = "Sobreviviste, pero la presión no terminó en zona verde."
                self.terminar(False)
        else:
            self.turno += 1
            self.clima = self.sortear_clima()

    def terminar(self, gano):
        self.fase = "ganado" if gano else "perdido"
        self.state.set_flag("valvulas_superadas", gano)
        if gano:
            self.state.add("curiosidad", 1)

    def consejo(self):
        if self.presion > self.VERDE_MAX:
            estado = "La presión está ALTA"
        elif self.presion < self.VERDE_MIN:
            estado = "La presión está BAJA"
        elif self.presion > 60:
            estado = "La presión viene subiendo"
        elif self.presion < 40:
            estado = "La presión viene bajando"
        else:
            estado = "La presión está bien"
        calientes = [v["nombre"] for v in self.VALVULAS if self.rachas[v["id"]] >= 2]
        extra = f"  ·  Recalentada: {', '.join(calientes)}" if calientes else ""
        return f"{estado}.{extra}"

    # ---------------- eventos ----------------
    def handle_event(self, event):
        if self.input_cooldown > 0:
            return
        if event.type == pygame.KEYDOWN:
            if self.fase == "intro" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.fase = "jugando"
            elif self.fase == "perdido" and event.key == pygame.K_r:
                self.reiniciar()
            elif self.fase == "ganado" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.manager.replace(EndingScene(self.manager, self.state, self.audio))
            elif self.fase == "jugando":
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.avanzar()
                elif event.key == pygame.K_1:
                    self.alternar(0)
                elif event.key == pygame.K_2:
                    self.alternar(1)
                elif event.key == pygame.K_3:
                    self.alternar(2)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.fase == "intro":
                self.fase = "jugando"
            elif self.fase == "jugando":
                for i in range(3):
                    x, y, w, h = self.rect_valvula(i)
                    if x <= event.pos[0] <= x + w and y <= event.pos[1] <= y + h:
                        self.alternar(i)
                        return
                x, y, w, h = self.rect_boton()
                if x <= event.pos[0] <= x + w and y <= event.pos[1] <= y + h:
                    self.avanzar()

    def update(self, dt):
        if self.input_cooldown > 0:
            self.input_cooldown -= dt
        dif = self.presion - self.presion_vista
        self.presion_vista += max(-60 * dt, min(60 * dt, dif))

    # ---------------- dibujo ----------------
    def rect_valvula(self, i):
        return (190 + i * 230, 160, 210, 150)

    def rect_boton(self):
        return (330, 462, 300, 50)

    def texto(self, surf, txt, pos, fuente=None, color=(235, 235, 235), centro=False):
        img = (fuente or self.f).render(txt, True, color)
        r = img.get_rect(center=pos) if centro else img.get_rect(topleft=pos)
        surf.blit(img, r)

    def y_presion(self, p):
        return 430 - int(p / 100 * 280)       # 0 -> y=430 ; 100 -> y=150

    def dibujar_medidor(self, s):
        x, w = 60, 70
        zonas = [(0, self.ROJO_MIN, (200, 70, 70)), (self.ROJO_MIN, self.VERDE_MIN, (230, 190, 70)),
                 (self.VERDE_MIN, self.VERDE_MAX, (80, 190, 110)),
                 (self.VERDE_MAX, self.ROJO_MAX, (230, 190, 70)), (self.ROJO_MAX, 100, (200, 70, 70))]
        for a, b, col in zonas:
            pygame.draw.rect(s, col, (x, self.y_presion(b), w, self.y_presion(a) - self.y_presion(b)))
        pygame.draw.rect(s, (230, 230, 240), (x, 150, w, 280), 2)
        y = self.y_presion(self.presion_vista)
        pygame.draw.polygon(s, (255, 255, 255), [(x - 4, y), (x - 24, y - 12), (x - 24, y + 12)])
        pygame.draw.line(s, (255, 255, 255), (x, y), (x + w, y), 3)
        self.texto(s, "PRESIÓN", (x + w // 2, 132), self.f_peq, centro=True)
        self.texto(s, f"{int(round(self.presion_vista))}", (x + w // 2, 448), self.f, centro=True)
        self.texto(s, "ROJO = explota", (x + w // 2, 472), self.f_peq, (240, 130, 130), centro=True)
        self.texto(s, "VERDE = seguro", (x + w // 2, 492), self.f_peq, (130, 220, 150), centro=True)

    def dibujar_valvula(self, s, i):
        v = self.VALVULAS[i]
        x, y, w, h = self.rect_valvula(i)
        abierta = self.abiertas[v["id"]]
        col = v["color"]
        pygame.draw.rect(s, (46, 54, 74) if abierta else (30, 36, 52), (x, y, w, h), border_radius=14)
        pygame.draw.rect(s, col if abierta else (90, 98, 120), (x, y, w, h), 4 if abierta else 2, border_radius=14)
        self.texto(s, f"[{i + 1}] {v['nombre']}", (x + w // 2, y + 20), self.f, col, centro=True)
        # rueda de la válvula
        cx, cy = x + w // 2, y + 72
        pygame.draw.circle(s, col if abierta else (80, 86, 104), (cx, cy), 26, 5)
        pygame.draw.line(s, col if abierta else (80, 86, 104), (cx - 26, cy), (cx + 26, cy), 4)
        pygame.draw.line(s, col if abierta else (80, 86, 104), (cx, cy - 26), (cx, cy + 26), 4)
        ef = self.eficacia(self.rachas[v["id"]]) * 100
        color_ef = (240, 130, 110) if ef < 60 else (col if abierta else (140, 146, 165))
        estado = "ABIERTA" if abierta else "cerrada"
        self.texto(s, f"{estado} · eficacia {ef:.0f}%", (x + w // 2, y + 112),
                   self.f_peq, color_ef, centro=True)
        self.texto(s, v["desc"], (x + w // 2, y + 134), self.f_peq, (190, 195, 210), centro=True)

    def draw(self):
        s = self.manager.screen
        s.fill((20, 24, 36))
        self.texto(s, "PRESIÓN DE GAS", (WIDTH // 2, 28), self.f_titulo, centro=True)
        self.texto(s, f"Turno {min(self.turno, self.TOTAL_TURNOS)}/{self.TOTAL_TURNOS}", (WIDTH - 150, 18))
        self.texto(s, self.mensaje, (WIDTH // 2, 70), self.f, self.color_msg, centro=True)
        if self.fase == "jugando":
            cl = self.CLIMAS[self.clima]
            pygame.draw.rect(s, (36, 42, 60), (190, 92, 670, 34), border_radius=10)
            pygame.draw.rect(s, cl["color"], (190, 92, 670, 34), 2, border_radius=10)
            self.texto(s, f"CLIMA DE ESTE TURNO: {cl['nombre']} ({cl['texto']})", (WIDTH // 2 + 15, 109),
                       self.f_peq, cl["color"], centro=True)
            self.texto(s, self.consejo(), (WIDTH // 2 + 15, 138), self.f_peq, (250, 225, 140), centro=True)

        self.dibujar_medidor(s)
        for i in range(3):
            self.dibujar_valvula(s, i)

        # panel de probabilidades (condicionales a las válvulas elegidas)
        abiertas = self.lista_abiertas()
        pr = self.probabilidades(abiertas, self.rachas, self.clima)
        if abiertas:
            nombres = " + ".join(v["nombre"] for v in self.VALVULAS if v["id"] in abiertas)
            titulo = f"Con {nombres} abierta(s), en este turno la chance de que la presión..."
        else:
            titulo = "Con todas las válvulas cerradas, en este turno la chance de que la presión..."
        self.texto(s, titulo, (190, 322), self.f_peq, (200, 205, 220))
        colores = {"sube": (230, 90, 90), "igual": (100, 210, 130), "baja": (90, 150, 240)}
        for k, ev in enumerate(("sube", "igual", "baja")):
            y = 348 + k * 31
            self.texto(s, self.NOMBRE_EVENTO[ev], (190, y), self.f_peq, colores[ev])
            pygame.draw.rect(s, (50, 56, 76), (330, y, 400, 18), border_radius=9)
            pygame.draw.rect(s, colores[ev], (330, y, int(400 * pr[ev]), 18), border_radius=9)
            self.texto(s, f"{pr[ev] * 100:.0f}%", (745, y - 2), self.f_peq, colores[ev])

        bx, by, bw, bh = self.rect_boton()
        pygame.draw.rect(s, (60, 130, 200), (bx, by, bw, bh), border_radius=12)
        self.texto(s, "AVANZAR TURNO (ESPACIO)", (bx + bw // 2, by + bh // 2), self.f, centro=True)

        if self.fase == "intro":
            self.panel_intro(s)
        elif self.finalizado:
            self.panel_final(s)

    def panel_intro(self, s):
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 225))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        self.texto(s, "¿CÓMO SE JUEGA?", (c, 50), self.f_titulo, (250, 225, 140), centro=True)
        lineas = [
            "Una planta de gas tiene una PRESIÓN (la aguja de la izquierda).",
            "Tenés que mantenerla en la zona VERDE durante 10 turnos.",
            "Si llega a la zona ROJA, el sistema explota.",
            "Tenés 3 válvulas (clic o teclas 1, 2, 3 para abrirlas o cerrarlas):",
            "   • ENTRADA: tiende a SUBIR la presión.",
            "   • SALIDA: tiende a BAJAR la presión.",
            "   • REGULADOR: tiende a MANTENERLA igual.",
            "Cada turno hay un CLIMA que empuja la presión (arriba lo ves).",
            "¡Ojo! Una válvula abierta mucho tiempo se RECALIENTA y rinde menos.",
            "Hay que ir cambiando de válvulas. Abajo ves la chance de cada resultado.",
            "Es azar: una válvula sube la chance, pero no la asegura.",
            "Cuando elijas, apretá ESPACIO para avanzar el turno.",
        ]
        for k, t in enumerate(lineas):
            self.texto(s, t, (c, 105 + k * 32), self.f, centro=True)
        self.texto(s, "Clic o ESPACIO para empezar", (c, HEIGHT - 30), self.f, (250, 225, 140), centro=True)

    def prob_condicional(self, vid, evento):
        """P(evento | válvula abierta) con los datos de la partida: P(A y B) / P(B)."""
        n = len(self.historial)
        b = sum(1 for ab, ev, cl in self.historial if vid in ab)
        ayb = sum(1 for ab, ev, cl in self.historial if vid in ab and ev == evento)
        return n, b, ayb

    def panel_final(self, s):
        gano = self.fase == "ganado"
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 220))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        self.texto(s, "¡SISTEMA ESTABILIZADO!" if gano else "SISTEMA FALLIDO", (c, 50),
                   self.f_titulo, (250, 225, 140), centro=True)
        self.texto(s, self.motivo, (c, 92), self.f, centro=True)
        self.texto(s, "Probabilidad condicional con tus decisiones:  P(A | B) = P(A y B) / P(B)",
                   (c, 140), self.f_peq, (200, 205, 220), centro=True)
        y = 175
        for v in self.VALVULAS:
            n, b, ayb = self.prob_condicional(v["id"], v["evento"])
            ev = self.NOMBRE_EVENTO[v["evento"]].lower()
            etiqueta = f"P({ev} | {v['nombre']} abierta)"
            if b == 0:
                linea = f"{etiqueta}: no abriste esta válvula en ningún turno."
            else:
                total_a = sum(1 for h in self.historial if h[1] == v["evento"])
                linea = (f"{etiqueta} = ({ayb}/{n}) / ({b}/{n}) = {ayb / b * 100:.0f}%"
                         f"   (sin condición: {total_a / n * 100:.0f}%)")
            self.texto(s, linea, (c, y), self.f_peq, v["color"], centro=True)
            y += 34
        cerradas = len(self.historial)
        self.texto(s, "Idea clave: lo que decidís cambia las probabilidades del resultado.",
                   (c, y + 20), self.f_peq, (180, 185, 200), centro=True)
        # historial en íconos
        x0 = c - len(self.historial) * 32 // 2
        for k, (ab, ev, cl) in enumerate(self.historial):
            col = {"sube": (230, 90, 90), "igual": (100, 210, 130), "baja": (90, 150, 240)}[ev]
            pygame.draw.circle(s, col, (x0 + k * 32 + 14, y + 80), 12)
            self.texto(s, {"sube": "↑", "igual": "=", "baja": "↓"}[ev], (x0 + k * 32 + 14, y + 80),
                       self.f_peq, (20, 20, 30), centro=True)
        self.texto(s, "Historial de turnos (↑ subió · = se mantuvo · ↓ bajó)", (c, y + 108),
                   self.f_peq, (150, 158, 180), centro=True)
        pie = "ESPACIO para continuar" if gano else "R para reintentar"
        self.texto(s, pie, (c, HEIGHT - 30), self.f, (250, 225, 140), centro=True)
