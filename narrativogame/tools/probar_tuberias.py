"""
Prueba aislada del minijuego 5 (tuberias).

    python tools\\probar_tuberias.py          abre SOLO el minijuego 5 en una ventana
    python tools\\probar_tuberias.py --test   verificaciones automaticas, sin ventana

No modifica ningun archivo del proyecto.
"""
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(RAIZ)                      # las escenas cargan assets/ y narrative/ con rutas relativas
sys.path.insert(0, RAIZ)


class AudioFalso:
    def play_click(self): pass
    def play_ambience(self): pass
    def stop_ambience(self): pass


def abrir_ventana():
    import pygame
    from settings import WIDTH, HEIGHT, FPS
    from engine.scene_manager import SceneManager
    from engine.audio import Audio
    from game.state import GameState
    from scenes.pipes import PipesScene

    pygame.init()
    try:
        pygame.mixer.init()
        audio = Audio()
    except Exception as e:
        print("Sin audio real, uso audio falso:", e)
        audio = AudioFalso()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Prueba - Minijuego 5")
    clock = pygame.time.Clock()
    state = GameState()
    manager = SceneManager(screen)
    manager.push(PipesScene(manager, state, audio))
    while True:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                print("stats:", state.stats)
                print("flags:", state.flags)
                pygame.quit()
                return
            manager.handle_event(event)
        manager.update(dt)
        manager.draw()
        pygame.display.flip()


def verificar():
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    import random
    import pygame
    from settings import WIDTH, HEIGHT
    from engine.scene_manager import SceneManager
    from game.state import GameState
    import scenes.pipes as P

    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    ok = True

    def check(nombre, cond):
        nonlocal ok
        print(("OK    " if cond else "FALLA ") + nombre)
        ok = ok and cond

    # 1) niveles: siempre resolubles y nunca entregados resueltos
    rng = random.Random(1)
    resolubles = sin_resolver = mismas_piezas = extremos_con_pieza = True
    for _ in range(300):
        grid, ent, sal, camino = P.generar_nivel(rng)
        ev = P.evaluar(grid, ent, sal)
        resolubles &= ev["conectado"] and not ev["extremos"] and len(ev["mojadas"]) == len(camino)
        g = P.desordenar(grid, camino, ent, sal, rng)
        e2 = P.evaluar(g, ent, sal)
        sin_resolver &= (not e2["conectado"]) or bool(e2["extremos"])
        cuenta = lambda gg: sorted((c.tipo, c.oxidada) for f in gg for c in f)
        mismas_piezas &= cuenta(grid) == cuenta(g)
        extremos_con_pieza &= g[ent][0].es_tubo and g[sal][P.COLS - 1].es_tubo
    check("300 niveles generados son resolubles (misma funcion evaluar)", resolubles)
    check("ningun nivel se entrega ya resuelto", sin_resolver)
    check("desordenar conserva el conjunto de piezas", mismas_piezas)
    check("la entrada y la salida siempre tienen tuberia al empezar", extremos_con_pieza)

    # 2) conexiones, obstrucciones, extremos abiertos
    grid, ent, sal, camino = P.generar_nivel(random.Random(7))
    r, c = camino[len(camino) // 2]
    guardada = grid[r][c]
    grid[r][c] = P.Celda("escombro")
    ev = P.evaluar(grid, ent, sal)
    check("un escombro en el camino corta la conexion y se reporta obstruccion",
          (not ev["conectado"]) and any(m == "obstruccion" for _, _, m in ev["extremos"]))
    grid[r][c] = P.Celda("vacio")
    ev = P.evaluar(grid, ent, sal)
    check("una celda vacia en el camino deja recorrido incompleto",
          (not ev["conectado"]) and any(m == "vacio" for _, _, m in ev["extremos"]))
    grid[r][c] = guardada
    guardada.rot = (guardada.rot + 1) % 4
    ev = P.evaluar(grid, ent, sal)
    check("girar una pieza del camino rompe la conexion", not ev["conectado"] or bool(ev["extremos"]))

    # 3) modelo: la ley exacta suma 1, coincide con la esperanza y con Monte Carlo
    grupos = {(0, False): 3, (0, True): 1, (1, False): 2, (2, True): 2}
    pres = 0.6
    pmf = P.pmf_fugas(grupos, pres)
    esp = sum(k * p for k, p in enumerate(pmf))
    check("pmf suma 1", abs(sum(pmf) - 1) < 1e-9)
    check("E[K] de la pmf = suma n*p", abs(esp - P.esperanza_fugas(grupos, pres)) < 1e-9)
    rng = random.Random(3)
    n_sim, ceros = 40000, 0
    for _ in range(n_sim):
        k = sum(1 for (z, ox), n in grupos.items()
                for _ in range(n) if rng.random() < P.prob_fuga(z, ox, pres))
        ceros += (k == 0)
    check(f"Monte Carlo P(K=0)={ceros / n_sim:.3f} vs exacta {pmf[0]:.3f}", abs(ceros / n_sim - pmf[0]) < 0.01)
    check("p mayor cerca de la entrada y en oxidadas",
          P.prob_fuga(0, False, 1) > P.prob_fuga(2, False, 1) and P.prob_fuga(0, True, 1) > P.prob_fuga(0, False, 1))

    # 4) escena: fases, controles, victoria, derrota, reintento, continuar
    def nueva(semilla):
        st = GameState()
        m = SceneManager(screen)
        sc = P.PipesScene(m, st, AudioFalso(), rng=random.Random(semilla))
        m.push(sc)
        sc.input_cooldown = 0
        return m, sc, st

    def tecla(sc, k):
        sc.handle_event(pygame.event.Event(pygame.KEYDOWN, key=k))

    m, sc, st = nueva(5)
    tecla(sc, pygame.K_SPACE)
    check("ESPACIO inicia el juego desde la intro", sc.fase == "jugando")
    cel = sc.grid[sc.cursor[0]][sc.cursor[1]]
    antes = cel.rot
    tecla(sc, pygame.K_e)
    check("E gira la pieza bajo el cursor", (cel.rot - antes) % 4 == 1 or not cel.es_tubo)
    tecla(sc, pygame.K_RIGHT)
    check("las flechas mueven el cursor", sc.cursor[1] == 1)
    a, b = sc.cursor, (sc.cursor[0], 2)
    ca, cb = sc.grid[a[0]][a[1]], sc.grid[b[0]][b[1]]
    if ca.es_tubo and cb.tipo != "escombro":
        tecla(sc, pygame.K_SPACE); tecla(sc, pygame.K_RIGHT); tecla(sc, pygame.K_SPACE)
        check("agarrar y soltar intercambia piezas", sc.grid[a[0]][a[1]] is cb and sc.grid[b[0]][b[1]] is ca)
    draw_ok = True
    try:
        sc.draw()
    except Exception as e:
        draw_ok = False
        print("   draw fallo:", repr(e))
    check("draw() corre sin errores en 'jugando'", draw_ok)

    # derrota: sin conexion el nivel sube hasta 100
    m, sc, st = nueva(11)
    tecla(sc, pygame.K_SPACE)
    t = 0
    while sc.fase == "jugando" and t < 1200:
        sc.update(0.1); t += 1
    check("sin conectar, la habitacion se inunda (derrota)", sc.fase == "perdido")
    check("la derrota se registra en el estado", st.flags.get("tuberias_superadas") is False
          and st.stats.get("tuberias_intentos") == 1)
    sc.draw()
    tecla(sc, pygame.K_r)
    check("R reintenta tras perder", sc.fase == "jugando" and sc.nivel == P.NIVEL_INICIAL)

    # victoria: conexion completa. Se compara dejar las piezas oxidadas en el
    # camino contra cambiarlas por sanas (la decision que el modelo debe premiar).
    def partida(semilla, quitar_oxido):
        m, sc, st = nueva(100 + semilla)
        tecla(sc, pygame.K_SPACE)
        g, e, sl, cam = P.generar_nivel(random.Random(semilla))
        if quitar_oxido:
            for r, c in cam:
                g[r][c].oxidada = False
        sc.grid, sc.ent, sc.sal = g, e, sl
        t = 0
        while sc.fase == "jugando" and t < 1200:
            sc.update(0.1); t += 1
        return m, sc, st

    n = 40
    con_ox = sum(partida(s, False)[1].fase == "ganado" for s in range(n))
    sin_ox = sum(partida(s, True)[1].fase == "ganado" for s in range(n))
    print(f"      victorias con conexion completa: oxidadas en el camino {con_ox}/{n}, cambiadas por sanas {sin_ox}/{n}")
    check("con conexion completa y piezas sanas casi siempre se gana", sin_ox >= int(n * 0.9))
    check("dejar piezas oxidadas en el camino reduce las victorias (las decisiones importan)", con_ox < sin_ox)
    m, sc, st = partida(0, True)
    check("la partida de prueba termino en victoria", sc.fase == "ganado")
    sc.draw()
    check("la victoria se registra en el estado",
          st.flags.get("tuberias_superadas") is True and st.stats.get("curiosidad") == 1)
    tecla(sc, pygame.K_RETURN)
    check("ENTER tras ganar continua a la siguiente escena", type(m.current()).__name__ == "EndingScene")

    print("\nRESULTADO:", "TODO OK" if ok else "HAY FALLAS")
    return 0 if ok else 1


if __name__ == "__main__":
    if "--test" in sys.argv:
        sys.exit(verificar())
    abrir_ventana()