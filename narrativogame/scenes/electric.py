import math
import random
import pygame

from settings import WIDTH, HEIGHT
from engine.scene_manager import Scene
from scenes.drones import DronesScene


class ElectricScene(Scene):
    """
    MINIJUEGO 1 - Sistema eléctrico y fantasmas.

    Cómo se juega:
        La zona está a oscuras y un fantasma se acerca. En cada ronda hay 3 fusibles,
        y cada uno muestra su % de funcionar. Elegís uno para instalarlo:
            - si funciona  -> se enciende una luz
            - si se quema  -> el fantasma se acerca
        Ganás con 3 luces antes de 3 fallos. La luz ahuyenta a los fantasmas.

    Matemática (se explica al final):
        Instalar un fusible es un ensayo de Bernoulli (funciona / se quema).
        El total de aciertos X en n intentos sigue una binomial cuando todos
        tienen la misma p; con distinta p se usa su generalización (acá la
        calculamos exacta con programación dinámica).
    """

    ACIERTOS_META = 3
    FALLOS_MAX = 3
    CALIDADES = [0.15, 0.30, 0.50, 0.70, 0.90]

    # ---------------- matemática ----------------
    @staticmethod
    def distribucion(ps):
        """d[x] = P(exactamente x éxitos) en ensayos independientes con prob. ps[i]."""
        d = [1.0]
        for p in ps:
            nuevo = [0.0] * (len(d) + 1)
            for x, pr in enumerate(d):
                nuevo[x] += pr * (1 - p)
                nuevo[x + 1] += pr * p
            d = nuevo
        return d

    # ---------------- inicio ----------------
    def __init__(self, manager, state, audio):
        super().__init__(manager)
        self.state = state
        self.audio = audio
        self.f_titulo = pygame.font.Font(None, 48)
        self.f = pygame.font.Font(None, 28)
        self.f_peq = pygame.font.Font(None, 22)
        self.input_cooldown = 0.0
        self.reiniciar(intro=True)

    def on_enter(self):
        self.input_cooldown = 0.4

    def reiniciar(self, intro=False):
        self.fase = "intro" if intro else "jugando"
        self.aciertos = 0
        self.fallos = 0
        self.historial_p = []
        self.mensaje = "Elegí un fusible. Mirá su porcentaje."
        self.color_msg = (235, 235, 235)
        self.ghost_huida = 0.0
        self.destello = 0.0
        self.tiempo = 0.0
        self.ronda_nueva()
        self.sync_state()

    def ronda_nueva(self):
        self.fusibles = random.sample(self.CALIDADES, 3)

    def sync_state(self):
        self.state.stats["fusibles_intentados"] = len(self.historial_p)
        self.state.stats["fusibles_correctos"] = self.aciertos
        self.state.stats["fusibles_incorrectos"] = self.fallos
        self.state.flags["luces_restauradas"] = self.fase == "ganado"
        self.state.flags["fantasmas_ahuyentados"] = self.fase == "ganado"

    # ---------------- lógica ----------------
    def elegir(self, i):
        if self.fase != "jugando":
            return
        p = self.fusibles[i]
        self.historial_p.append(p)
        if random.random() < p:
            self.aciertos += 1
            self.destello = 0.4
            self.mensaje = "¡Funcionó! Se encendió una luz."
            self.color_msg = (250, 225, 120)
        else:
            self.fallos += 1
            self.mensaje = "¡Se quemó! El fantasma se acerca..."
            self.color_msg = (240, 110, 110)
        if self.aciertos >= self.ACIERTOS_META:
            self.fase = "ganado"
            self.ghost_huida = 1.5
        elif self.fallos >= self.FALLOS_MAX:
            self.fase = "perdido"
        else:
            self.ronda_nueva()
        self.sync_state()

    def rect_fusible(self, i):
        return (150 + i * 230, 290, 200, 170)

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
                self.manager.replace(DronesScene(self.manager, self.state, self.audio))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.fase == "intro":
                self.fase = "jugando"
            elif self.fase == "jugando":
                for i in range(3):
                    x, y, w, h = self.rect_fusible(i)
                    if x <= event.pos[0] <= x + w and y <= event.pos[1] <= y + h:
                        if self.audio:
                            self.audio.play_click()
                        self.elegir(i)
                        break

    def update(self, dt):
        self.tiempo += dt
        if self.input_cooldown > 0:
            self.input_cooldown -= dt
        if self.destello > 0:
            self.destello -= dt
        if self.ghost_huida > 0:
            self.ghost_huida -= dt

    # ---------------- dibujo ----------------
    def texto(self, surf, txt, pos, fuente=None, color=(235, 235, 235), centro=False):
        img = (fuente or self.f).render(txt, True, color)
        r = img.get_rect(center=pos) if centro else img.get_rect(topleft=pos)
        surf.blit(img, r)

    def dibujar_fantasma(self, s, x, y, alpha_boost=0):
        c = (200, 210, 235)
        pygame.draw.circle(s, c, (x, y), 40)
        pygame.draw.polygon(s, c, [(x - 40, y), (x - 40, y + 70), (x - 20, y + 52), (x, y + 72),
                                   (x + 20, y + 52), (x + 40, y + 70), (x + 40, y)])
        pygame.draw.circle(s, (30, 35, 50), (x - 14, y - 4), 6)
        pygame.draw.circle(s, (30, 35, 50), (x + 14, y - 4), 6)
        pygame.draw.circle(s, (30, 35, 50), (x, y + 16), 7, 2)

    def draw(self):
        s = self.manager.screen
        luz = self.fase == "ganado"
        s.fill((236, 224, 180) if luz else (14, 17, 28))

        # suelo
        pygame.draw.rect(s, (120, 100, 80) if luz else (24, 28, 40), (0, 250, WIDTH, 40))

        # personaje con linterna
        pygame.draw.circle(s, (240, 200, 160), (110, 215), 16)
        pygame.draw.rect(s, (70, 110, 170), (96, 230, 28, 40), border_radius=6)
        if not luz:
            pygame.draw.polygon(s, (60, 60, 40), [(125, 235), (330, 190), (330, 280)])

        # fantasma
        if self.fase in ("jugando", "perdido", "intro"):
            avance = min(self.fallos / self.FALLOS_MAX, 1.0)
            gx = int(880 - avance * 710)
            gy = 190 + int(math.sin(self.tiempo * 2) * 8)
            self.dibujar_fantasma(s, gx, gy)
        elif self.ghost_huida > 0:
            t = 1 - self.ghost_huida / 1.5
            self.dibujar_fantasma(s, int(400 + t * 700), int(190 - t * 120))

        # título y bombillas (aciertos)
        self.texto(s, "SISTEMA ELÉCTRICO", (WIDTH // 2, 30), self.f_titulo,
                   (60, 50, 30) if luz else (235, 235, 235), centro=True)
        for k in range(self.ACIERTOS_META):
            on = k < self.aciertos
            col = (255, 230, 110) if on else (60, 66, 84)
            pygame.draw.circle(s, col, (WIDTH // 2 - 60 + k * 60, 85), 18)
            pygame.draw.circle(s, (200, 200, 210), (WIDTH // 2 - 60 + k * 60, 85), 18, 2)
        self.texto(s, f"Luces: {self.aciertos}/{self.ACIERTOS_META}     Fallos: {self.fallos}/{self.FALLOS_MAX}",
                   (WIDTH // 2, 125), self.f_peq, (60, 50, 30) if luz else (200, 205, 220), centro=True)
        self.texto(s, self.mensaje, (WIDTH // 2, 155), self.f, self.color_msg if not luz else (90, 70, 20), centro=True)

        # caja de fusibles
        if self.fase in ("jugando", "intro"):
            self.texto(s, "¿Qué fusible instalás?", (WIDTH // 2, 272), self.f_peq, (200, 205, 220), centro=True)
            mx, my = pygame.mouse.get_pos() if hasattr(pygame, "mouse") else (0, 0)
            for i, p in enumerate(self.fusibles):
                x, y, w, h = self.rect_fusible(i)
                hover = x <= mx <= x + w and y <= my <= y + h and self.fase == "jugando"
                pygame.draw.rect(s, (52, 60, 82) if hover else (36, 42, 60), (x, y, w, h), border_radius=14)
                pygame.draw.rect(s, (240, 240, 250) if hover else (110, 120, 150), (x, y, w, h), 2, border_radius=14)
                col = (90, 210, 120) if p >= 0.7 else (240, 200, 80) if p >= 0.4 else (230, 90, 90)
                # fusible
                pygame.draw.rect(s, (200, 205, 215), (x + w // 2 - 14, y + 16, 28, 56), border_radius=8)
                pygame.draw.rect(s, col, (x + w // 2 - 8, y + 24, 16, 40), border_radius=5)
                # medidor
                pygame.draw.rect(s, (60, 66, 84), (x + 20, y + 92, w - 40, 14), border_radius=7)
                pygame.draw.rect(s, col, (x + 20, y + 92, int((w - 40) * p), 14), border_radius=7)
                self.texto(s, f"{int(p * 100)}%", (x + w // 2, y + 128), self.f, col, centro=True)
                self.texto(s, "de funcionar", (x + w // 2, y + 150), self.f_peq, (170, 175, 195), centro=True)

        if self.destello > 0:
            fl = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            fl.fill((255, 240, 160, int(120 * self.destello / 0.4)))
            s.blit(fl, (0, 0))

        if self.fase == "intro":
            self.panel_intro(s)
        elif self.fase in ("ganado", "perdido"):
            self.panel_final(s)

    def panel_intro(self, s):
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 215))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        self.texto(s, "¿CÓMO SE JUEGA?", (c, 80), self.f_titulo, (250, 225, 140), centro=True)
        lineas = [
            "Es de noche, no hay luz y un fantasma se te acerca.",
            "En cada ronda hay 3 fusibles. Cada uno muestra su % de funcionar.",
            "Hacé clic en un fusible para instalarlo:",
            "   • Si funciona, se enciende una luz.",
            "   • Si se quema, el fantasma se acerca un paso.",
            "Ganás si encendés 3 luces antes de 3 fallos.",
            "Consejo: los fusibles verdes (% alto) fallan menos.",
        ]
        for k, t in enumerate(lineas):
            self.texto(s, t, (c, 150 + k * 36), self.f, centro=True)
        self.texto(s, "Clic o ESPACIO para empezar", (c, HEIGHT - 50), self.f, (250, 225, 140), centro=True)

    def panel_final(self, s):
        gano = self.fase == "ganado"
        if gano and self.ghost_huida > 0:
            return
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 200))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        self.texto(s, "¡LUCES ENCENDIDAS! Los fantasmas huyeron." if gano else "El fantasma te alcanzó...",
                   (c, 70), self.f_titulo, (250, 225, 140), centro=True)
        n = len(self.historial_p)
        d = self.distribucion(self.historial_p)
        esperado = sum(self.historial_p)
        q = d[self.aciertos] * 100
        lineas = [
            f"Instalaste {n} fusibles: {self.aciertos} funcionaron y {self.fallos} se quemaron.",
            "Cada fusible fue un ensayo de Bernoulli: funciona (éxito) o se quema (fracaso).",
            f"Por los % que elegiste, esperabas {esperado:.1f} aciertos y lograste {self.aciertos}.",
            f"Probabilidad de sacar exactamente {self.aciertos} aciertos en {n} intentos: {q:.0f}%",
        ]
        for k, t in enumerate(lineas):
            self.texto(s, t, (c, 130 + k * 32), self.f_peq, centro=True)
        # barras de la distribución del nº de aciertos
        bw, base, alto = 40, 440, 150
        x = c - len(d) * (bw + 10) // 2
        mx = max(d)
        for k, pr in enumerate(d):
            h = int(alto * pr / mx)
            col = (110, 220, 150) if k == self.aciertos else (110, 130, 170)
            pygame.draw.rect(s, col, (x, base - h, bw, h))
            self.texto(s, str(k), (x + bw // 2, base + 14), self.f_peq, centro=True)
            self.texto(s, f"{pr * 100:.0f}%", (x + bw // 2, base - h - 14), self.f_peq, centro=True)
            x += bw + 10
        self.texto(s, "Cada barra: probabilidad de lograr esa cantidad de aciertos (verde = la tuya)",
                   (c, 480), self.f_peq, (180, 185, 200), centro=True)
        pie = "ESPACIO para continuar" if gano else "R para reintentar"
        self.texto(s, pie, (c, HEIGHT - 28), self.f, (250, 225, 140), centro=True)
