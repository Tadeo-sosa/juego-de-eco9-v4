import math
import random
import pygame

from settings import WIDTH, HEIGHT
from engine.scene_manager import Scene
from scenes.gas import ValvulasScene


class DronesScene(Scene):
    """
    MINIJUEGO 2 - Control de drones autodestructivos.

    Cómo se juega:
        Varios drones bajan A LA VEZ hacia tu base. Con una torreta tenés que
        derribarlos antes de que lleguen:
            1) Hacé clic en los drones que querés atacar (se marcan con una mira).
            2) Apretá ESPACIO para disparar a todos los marcados juntos.
        Cada drone muestra su % de ser derribado: cuanto MÁS CERCA está, más fácil
        es acertarle... pero tenés menos tiempo antes de que explote en la base.
        Disparar gasta interceptores (uno por objetivo) y la torreta tarda en recargar.

    Matemática (se explica al final):
        - Cada disparo a un drone = ensayo de Bernoulli (derriba / falla).
        - Un disparo a varios drones = varios ensayos en paralelo.
          Con igual p es una binomial; con distinta p usamos su generalización.
        - "Al menos j de m" es la distribución acumulada: P(X >= j).
    """

    OLEADAS = 3
    DRONES_POR_OLEADA = 5
    VIDA_BASE = 4
    MUNICION = 7
    RECARGA = 1.6
    ZONAS = [(0.35, 0.45), (0.70, 0.70), (1.01, 0.90)]   # (progreso máx, p)
    Y_INICIO, Y_BASE = 130, 395

    # ---------------- matemática ----------------
    @staticmethod
    def binomial_pmf(n, k, p):
        if k < 0 or k > n:
            return 0.0
        return math.comb(n, k) * (p ** k) * ((1 - p) ** (n - k))

    @classmethod
    def binomial_acumulada(cls, n, k, p):
        """P(X >= k), X ~ Binomial(n, p)."""
        return sum(cls.binomial_pmf(n, x, p) for x in range(max(k, 0), n + 1))

    @staticmethod
    def distribucion_paralela(ps):
        """d[x] = P(X = x) para ensayos independientes con probabilidades ps."""
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
        self.f_titulo = pygame.font.Font(None, 46)
        self.f = pygame.font.Font(None, 28)
        self.f_peq = pygame.font.Font(None, 22)
        self.input_cooldown = 0.0
        self.reiniciar(intro=True)

    def on_enter(self):
        self.input_cooldown = 0.4

    def reiniciar(self, intro=False):
        self.fase = "intro" if intro else "jugando"
        self.oleada = 0
        self.vida = self.VIDA_BASE
        self.exitos = 0
        self.fallos = 0
        self.historial_p = []
        self.recarga = 0.0
        self.destellos = []
        self.mensaje = "Marcá drones con clic y disparás con ESPACIO."
        self.color_msg = (235, 235, 235)
        self.nueva_oleada()

    @property
    def finalizado(self):
        return self.fase in ("ganado", "perdido")

    def nueva_oleada(self):
        self.oleada += 1
        self.municion = self.MUNICION
        n = self.DRONES_POR_OLEADA
        self.drones = [{
            "x": 130 + i * (WIDTH - 260) / (n - 1),
            "progreso": random.uniform(0.0, 0.25),
            "vel": random.uniform(0.055, 0.095),
            "vivo": True,
            "sel": False,
        } for i in range(n)]

    # ---------------- lógica ----------------
    def prob_drone(self, d):
        for limite, p in self.ZONAS:
            if d["progreso"] < limite:
                return p
        return self.ZONAS[-1][1]

    def pos_y(self, d):
        return self.Y_INICIO + d["progreso"] * (self.Y_BASE - self.Y_INICIO)

    def seleccionados(self):
        return [d for d in self.drones if d["vivo"] and d["sel"]]

    def disparar(self):
        objetivos = self.seleccionados()
        if self.fase != "jugando" or not objetivos:
            return
        if self.recarga > 0:
            self.mensaje = "La torreta se está recargando..."
            self.color_msg = (240, 200, 110)
            return
        if len(objetivos) > self.municion:
            self.mensaje = f"Solo te quedan {self.municion} interceptores. Marcá menos drones."
            self.color_msg = (240, 110, 110)
            return
        self.recarga = self.RECARGA
        self.municion -= len(objetivos)
        ok = 0
        for d in objetivos:                      # ensayos de Bernoulli en paralelo
            p = self.prob_drone(d)
            self.historial_p.append(p)
            d["sel"] = False
            if random.random() < p:
                d["vivo"] = False
                ok += 1
                self.exitos += 1
                self.destellos.append([d["x"], self.pos_y(d), 0.5, (90, 230, 130)])
            else:
                self.fallos += 1
                self.destellos.append([d["x"], self.pos_y(d), 0.5, (240, 90, 90)])
        self.mensaje = f"Disparaste a {len(objetivos)}: derribaste {ok}, fallaste {len(objetivos) - ok}."
        self.color_msg = (120, 230, 150) if ok else (240, 110, 110)
        self.comprobar_oleada()

    def comprobar_oleada(self):
        if self.finalizado or any(d["vivo"] for d in self.drones):
            return
        if self.oleada >= self.OLEADAS:
            self.terminar(self.vida > 0)
        else:
            self.nueva_oleada()
            self.mensaje = f"Oleada {self.oleada}/{self.OLEADAS}: ¡llegan más drones!"
            self.color_msg = (240, 220, 120)

    def terminar(self, gano):
        self.fase = "ganado" if gano else "perdido"
        self.state.add("drones_interceptados", self.exitos)
        self.state.add("drones_fallidos", self.fallos)
        self.state.set_flag("drones_controlados", gano)

    def update(self, dt):
        if self.input_cooldown > 0:
            self.input_cooldown -= dt
        if self.fase != "jugando":
            return
        self.recarga = max(0.0, self.recarga - dt)
        for dest in self.destellos:
            dest[2] -= dt
        self.destellos = [x for x in self.destellos if x[2] > 0]
        for d in self.drones:
            if not d["vivo"]:
                continue
            d["progreso"] += d["vel"] * dt
            if d["progreso"] >= 1.0:
                d["vivo"] = False
                d["sel"] = False
                self.vida -= 1
                self.destellos.append([d["x"], self.Y_BASE, 0.7, (255, 170, 60)])
                self.mensaje = "¡Un drone explotó en tu base!"
                self.color_msg = (255, 170, 60)
        if self.vida <= 0:
            self.terminar(False)
        else:
            self.comprobar_oleada()

    # ---------------- eventos ----------------
    def handle_event(self, event):
        if self.input_cooldown > 0:
            return
        if event.type == pygame.KEYDOWN:
            if self.fase == "intro" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self.fase = "jugando"
            elif event.key == pygame.K_r and self.fase == "perdido":
                self.reiniciar()
            elif event.key in (pygame.K_SPACE, pygame.K_RETURN):
                if self.fase == "ganado":
                    self.manager.replace(ValvulasScene(self.manager, self.state, self.audio))
                else:
                    self.disparar()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.fase == "intro":
                self.fase = "jugando"
            elif self.fase == "jugando":
                for d in self.drones:
                    if d["vivo"] and math.hypot(event.pos[0] - d["x"], event.pos[1] - self.pos_y(d)) < 40:
                        d["sel"] = not d["sel"]
                        if self.audio:
                            self.audio.play_click()
                        break

    # ---------------- dibujo ----------------
    def texto(self, surf, txt, pos, fuente=None, color=(235, 235, 235), centro=False):
        img = (fuente or self.f).render(txt, True, color)
        r = img.get_rect(center=pos) if centro else img.get_rect(topleft=pos)
        surf.blit(img, r)

    def color_p(self, p):
        return (110, 150, 230) if p < 0.5 else (240, 205, 100) if p < 0.8 else (240, 110, 100)

    def dibujar_drone(self, s, d):
        x, y = int(d["x"]), int(self.pos_y(d))
        p = self.prob_drone(d)
        col = self.color_p(p)
        for dx in (-26, 26):
            pygame.draw.line(s, (200, 205, 215), (x, y), (x + dx, y - 14), 3)
            pygame.draw.circle(s, (200, 205, 215), (x + dx, y - 14), 8, 2)
        pygame.draw.circle(s, col, (x, y), 16)
        if d["sel"]:
            pygame.draw.circle(s, (255, 255, 255), (x, y), 34, 3)
            pygame.draw.line(s, (255, 90, 90), (x - 44, y), (x + 44, y), 2)
            pygame.draw.line(s, (255, 90, 90), (x, y - 44), (x, y + 44), 2)
        self.texto(s, f"{int(p * 100)}%", (x, y + 32), self.f, col, centro=True)

    def draw(self):
        s = self.manager.screen
        s.fill((22, 28, 40))
        zonas = [(0.0, 0.35, (30, 38, 56), "LEJOS: difícil (45%)"),
                 (0.35, 0.70, (38, 46, 62), "MEDIO: normal (70%)"),
                 (0.70, 1.0, (60, 40, 46), "CERCA: fácil (90%) ¡peligro!")]
        for a, b, col, nombre in zonas:
            y0 = self.Y_INICIO + a * (self.Y_BASE - self.Y_INICIO)
            y1 = self.Y_INICIO + b * (self.Y_BASE - self.Y_INICIO)
            pygame.draw.rect(s, col, (0, y0, WIDTH, y1 - y0))
            self.texto(s, nombre, (12, y0 + 6), self.f_peq, (150, 158, 180))
        pygame.draw.line(s, (255, 120, 90), (0, self.Y_BASE + 18), (WIDTH, self.Y_BASE + 18), 3)

        self.texto(s, "CONTROL DE DRONES", (WIDTH // 2, 26), self.f_titulo, centro=True)
        self.texto(s, f"Oleada {self.oleada}/{self.OLEADAS}", (24, 14))
        self.texto(s, f"Base: {self.vida}/{self.VIDA_BASE}", (24, 40), color=(255, 170, 120))
        self.texto(s, f"Interceptores: {self.municion}", (WIDTH - 210, 14), color=(150, 220, 255))
        self.texto(s, self.mensaje, (WIDTH // 2, 80), color=self.color_msg, centro=True)

        for d in self.drones:
            if d["vivo"]:
                self.dibujar_drone(s, d)
        for x, y, t, col in self.destellos:
            pygame.draw.circle(s, col, (int(x), int(y)), int(10 + (0.7 - t) * 60), 3)

        # torreta
        pygame.draw.polygon(s, (170, 180, 195), [(WIDTH // 2 - 30, 448), (WIDTH // 2 + 30, 448), (WIDTH // 2, 420)])
        listo = 1 - self.recarga / self.RECARGA
        pygame.draw.rect(s, (70, 80, 95), (WIDTH // 2 - 60, 454, 120, 8), border_radius=4)
        pygame.draw.rect(s, (110, 220, 150), (WIDTH // 2 - 60, 454, int(120 * listo), 8), border_radius=4)

        self.panel_info(s)
        if self.fase == "intro":
            self.panel_intro(s)
        elif self.finalizado:
            self.panel_final(s)

    def panel_info(self, s):
        c = WIDTH // 2
        sel = self.seleccionados()
        if not sel:
            self.texto(s, "Clic en un drone para marcarlo · ESPACIO para disparar a los marcados",
                       (c, 486), self.f_peq, (180, 185, 200), centro=True)
            return
        ps = [self.prob_drone(d) for d in sel]
        d = self.distribucion_paralela(ps)
        m = len(ps)
        if m == 1:
            txt = f"Marcaste 1 drone: {ps[0] * 100:.0f}% de derribarlo."
        else:
            partes = [f"al menos {j}: {sum(d[j:]) * 100:.0f}%" for j in range(1, m + 1)]
            txt = f"Marcaste {m} drones. Chance de derribar " + " · ".join(partes)
        self.texto(s, txt, (c, 486), self.f_peq, (250, 225, 140), centro=True)
        self.texto(s, "(Cada disparo gasta 1 interceptor por drone marcado)", (c, 508), self.f_peq,
                   (150, 158, 180), centro=True)

    def panel_intro(self, s):
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 225))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        self.texto(s, "¿CÓMO SE JUEGA?", (c, 70), self.f_titulo, (250, 225, 140), centro=True)
        lineas = [
            "Drones explosivos bajan hacia tu base. ¡Tenés que derribarlos!",
            "1) Hacé clic en los drones que querés atacar (se marcan con una mira).",
            "2) Apretá ESPACIO para disparar a todos los marcados a la vez.",
            "Cada drone muestra su % de ser derribado. Cuanto más cerca, más fácil...",
            "...pero si un drone llega abajo, explota y la base pierde 1 de vida.",
            "Cada disparo gasta interceptores (7 por oleada) y la torreta tarda en recargar.",
            "Ganás si sobrevivís las 3 oleadas. Si disparás apurado, vas a quedarte sin munición.",
        ]
        for k, t in enumerate(lineas):
            self.texto(s, t, (c, 135 + k * 38), self.f, centro=True)
        self.texto(s, "Clic o ESPACIO para empezar", (c, HEIGHT - 45), self.f, (250, 225, 140), centro=True)

    def panel_final(self, s):
        vel = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        vel.fill((0, 0, 0, 215))
        s.blit(vel, (0, 0))
        c = WIDTH // 2
        gano = self.fase == "ganado"
        self.texto(s, "¡BASE A SALVO!" if gano else "LA BASE CAYÓ", (c, 60), self.f_titulo, (250, 225, 140), centro=True)
        n = len(self.historial_p)
        if n:
            d = self.distribucion_paralela(self.historial_p)
            esperado = sum(self.historial_p)
            p_ge = sum(d[self.exitos:]) * 100
            lineas = [
                f"Disparaste {n} veces: derribaste {self.exitos} y fallaste {self.fallos}.",
                "Cada disparo fue un ensayo de Bernoulli (derriba o falla).",
                f"Por los % de tus disparos esperabas derribar {esperado:.1f}.",
                f"Probabilidad de derribar al menos {self.exitos} con esos disparos: {p_ge:.0f}%",
            ]
            for k, t in enumerate(lineas):
                self.texto(s, t, (c, 115 + k * 30), self.f_peq, centro=True)
            ancho_b = max(10, min(40, 700 // len(d) - 4))
            base, alto = 440, 170
            x = c - len(d) * (ancho_b + 4) // 2
            mx = max(d)
            for k, pr in enumerate(d):
                h = int(alto * pr / mx)
                col = (110, 220, 150) if k == self.exitos else (110, 130, 170)
                pygame.draw.rect(s, col, (x, base - h, ancho_b, h))
                if len(d) <= 18:
                    self.texto(s, str(k), (x + ancho_b // 2, base + 12), self.f_peq, centro=True)
                x += ancho_b + 4
            self.texto(s, "Cada barra: probabilidad de derribar esa cantidad (verde = la tuya)",
                       (c, 478), self.f_peq, (180, 185, 200), centro=True)
        pie = "ESPACIO para continuar" if gano else "R para reintentar"
        self.texto(s, pie, (c, HEIGHT - 26), self.f, (250, 225, 140), centro=True)
