import threading
import time
import os

from . import archetypes
from . import config
from . import coach
from . import counterplan
from . import burn
from . import earlyitem
from . import lowgold
from . import patchdiff
from . import trend
from . import goldeff
from . import hybrid
from . import itemrules
from . import livemeta
from . import profiles
from . import runeoptions
from .ddragon import MODES, ROLE_NAMES, RANK_NAMES, REGION_NAMES, SPELL_NAMES_ES, ddragon
from .pets import recommend as recommend_pet
from .ugg import CONSUMABLE_IDS, ugg_client

# Posición de champ select -> rol de U.GG.
# Verificado con datos reales de U.GG: 1=Jungla, 2=Soporte, 3=ADC, 4=Top, 5=Mid.
POSITION_ROLE = {
    "TOP": "4",
    "JUNGLE": "1",
    "MID": "5",
    "BOTTOM": "3",
    "BOT": "3",
    "SUPPORT": "2",
}

# Cuánto se cachea una build de U.GG en memoria (no cambia cada minuto).
OVERVIEW_TTL = 30 * 60.0
# TTL de las opciones de runas calculadas al vuelo (para no pedir a U.GG en
# cada poll del overlay).
RUNE_OPTS_TTL = 10 * 60.0
# Tiempo que un campeón debe quedarse bajo el ratón para pedir su build.
HOVER_DEBOUNCE = 0.8


def _log(msg):
    try:
        log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
        os.makedirs(log_dir, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(os.path.join(log_dir, "app.log"), "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass


def fmt_time(seconds):
    try:
        s = int(seconds)
        return f"{s // 60:02d}:{s % 60:02d}"
    except Exception:
        return "00:00"


class Advisor:
    def __init__(self):
        self._lock = threading.Lock()
        self.overview = None
        self.overview_key = None
        self.overview_champ = None
        self.overview_loading = False
        self.matchups = None
        self.matchups_key = None
        self.matchups_loading = False
        self.matchups_error = None
        self.rune_builds = None
        self.rune_builds_key = None
        self.rune_builds_for = None
        self.rune_builds_loading = False
        self.last_update = 0
        self.last_live = None
        self.last_lcu = None
        self._last_matchups_shown = -1
        self._last_mu_tag = ""
        self.mock = False
        self.enemy_builds = {}
        self.enemy_builds_loading = set()
        self._dd_ver = None
        self.last_champ_key = None
        self.last_champ_name = None
        self.phase = "idle"
        self._overview_cache = {}
        self._preview_key = None
        self._preview_since = 0.0
        self.last_update = time.time()
        self._last_matchups_shown = -1
        self._last_mu_tag = ""
        # Opciones de runas calculadas al vuelo (con caché propia y TTL corto).
        self._rune_opts_cache = None
        self._rune_opts_key = None
        self._rune_opts_at = 0.0
        self._rune_opts_loading = False

    def _want_overview(self, champ_key, settings, mode_api, role, preview=False):
        key = (champ_key, mode_api, role, settings["rank"], settings["region"])
        if self.overview_key == key and self.overview:
            return
        if self.overview_loading and self.overview_key == key:
            return
        # Cache propia: al pasar el ratón por varios campeones no se vuelve
        # a descargar lo mismo, y volver a un campeón ya visto es instantáneo.
        cached = self._overview_cache.get(key)
        if cached and (time.time() - cached[1]) < OVERVIEW_TTL:
            with self._lock:
                self.overview = cached[0]
                self.overview_key = key
                self.overview_champ = champ_key
                self.overview_loading = False
            _log(f"[advisor] build de {champ_key} desde cache (rol {role})")
            return
        if preview:
            # Vista previa: se espera a que el campeón se mantenga un momento
            # bajo el ratón para no pedir una build por cada movimiento.
            now = time.time()
            if self._preview_key != key:
                self._preview_key = key
                self._preview_since = now
                return
            if now - self._preview_since < HOVER_DEBOUNCE:
                return
        self.overview_loading = True
        self.overview_key = key

        def work():
            try:
                data = ugg_client.get_overview(
                    champ_key, mode_api, role, settings["rank"], settings["region"]
                )
                with self._lock:
                    if data:
                        try:
                            data["trend"] = trend.compute(
                                ugg_client, data, champ_key, mode_api, role, settings["rank"], settings["region"])
                        except Exception as e:
                            _log(f"[advisor] trend falló: {e!r}")
                            data["trend"] = {}
                        data = patchdiff.filter_overview(data)
                        self.overview = data
                        self.overview_champ = champ_key
                        self._overview_cache[key] = (data, time.time())
                    self.overview_loading = False
                if data:
                    _log(f"[advisor] build cargada para {champ_key} "
                         f"({'vista previa' if preview else 'fijado'}, rol {role})")
            except Exception as e:
                print(f"[advisor] overview error: {e}")
                _log(f"[advisor] overview error para {champ_key}: {e!r}")
                with self._lock:
                    self.overview_loading = False

        threading.Thread(target=work, daemon=True).start()

    def _want_matchups(self, champ_key, settings, mode_api, role):
        key = (champ_key, mode_api, role, settings["rank"], settings["region"])
        if self.matchups_key == key and self.matchups is not None:
            return
        if self.matchups_loading and self.matchups_key == key:
            return
        self.matchups_loading = True
        self.matchups_key = key
        self.matchups_error = None

        def work():
            try:
                data = ugg_client.get_matchups(
                    champ_key, mode_api, role, settings["rank"], settings["region"]
                )
                with self._lock:
                    self.matchups = data or []
                    self.matchups_loading = False
                _log(f"[advisor] matchups cargados para {champ_key}: {len(data or [])} filas")
            except Exception as e:
                _log(f"[advisor] matchups ERROR para {champ_key}: {e!r}")
                with self._lock:
                    self.matchups_loading = False
                    self.matchups_error = f"{e!r}"

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _resolve_mode(settings, live, lcu):
        """Modo real de la partida (todos los modos) con U.GG; si no se puede
        detectar, usa el elegido en ajustes."""
        mode = None
        if live and live.get("mode"):
            mode = live["mode"]
        elif live and live.get("mode_hint") == "aram":
            mode = "aram"
        if not mode and lcu and lcu.get("mode"):
            mode = lcu["mode"]
        if mode not in MODES:
            mode = settings.get("mode", "ranked")
        if mode not in MODES:
            mode = "ranked"
        return mode

    def update(self, live, lcu, mock=False):
        v = ddragon.version
        if v and self._dd_ver and v != self._dd_ver:
            # Parche nuevo: descarta lo cacheado del parche anterior y vuelve a pedir datos.
            with self._lock:
                self.overview = None
                self._overview_cache.clear()
            self.last_champ_key = None
        if v:
            self._dd_ver = v
        settings = config.load_settings()
        self.mock = mock
        self.last_live = live
        self.last_lcu = lcu
        self.last_update = time.time()

        champ_key = None
        preview = False
        if live:
            self.phase = "in_game"
            champ = ddragon.champ_by_name(live.get("champion"))
            champ_key = champ["key"] if champ else None
        elif lcu and lcu.get("available"):
            # En champ select: vale lo que estés mirando, no hace falta
            # esperar a fijar el campeón.
            self.phase = "champ_select"
            if lcu.get("champion_id"):
                champ = ddragon.champ_by_key(lcu["champion_id"])
                champ_key = champ["key"] if champ else None
            preview = bool(lcu.get("hover_champion_id")) and not lcu.get("locked")
        else:
            self.phase = "idle"

        if not champ_key:
            return

        if champ_key != self.last_champ_key:
            _log(f"[advisor] campeón activo: {champ_key} "
                 f"({'vista previa' if preview else 'fijado'})")
        self.last_champ_key = champ_key
        mode = self._resolve_mode(settings, live, lcu)
        mode_api = MODES.get(mode, MODES["ranked"])[1]
        role = "6" if mode == "aram" else settings["role"]
        # En champ select manda la posición REAL de tu pick: si has picked top
        # pero tu config dice jungla, la build que sirve es la de top.
        if mode != "aram" and lcu and lcu.get("position"):
            role = POSITION_ROLE.get(lcu["position"], role)
        self._want_overview(champ_key, settings, mode_api, role, preview=preview)
        self._want_matchups(champ_key, settings, mode_api, role)
        self._want_rune_builds(champ_key, settings, mode_api, role)
        if not live:
            for _name, c in self._enemy_champs(None, lcu):
                self._want_enemy_build(c["key"], mode_api, settings)
            for _name, c in self._allies_champs(None, lcu):
                self._want_enemy_build(c["key"], mode_api, settings)

    def state(self):
        st = self._state_raw()
        try:
            earlyitem.attach(st, self.last_live)
        except Exception as e:
            _log(f"[advisor] early falló: {e!r}")
        try:
            patchdiff.annotate(st, (self.overview or {}).get("trend"))
            st["patch_warning"] = patchdiff.warning(st)
        except Exception as e:
            _log(f"[advisor] patchdiff falló: {e!r}")
            st["patch_warning"] = None
        try:
            st["burn"] = burn.compute(self.last_live)
        except Exception as e:
            _log(f"[advisor] burn falló: {e!r}")
            st["burn"] = None
        try:
            st["low_gold"] = lowgold.build(st, self.last_live, config.load_settings())
        except Exception as e:
            _log(f"[advisor] low_gold falló: {e!r}")
            st["low_gold"] = None
        return st

    def _state_raw(self):
        settings = config.load_settings()
        with self._lock:
            overview = self.overview
            overview_loading = self.overview_loading
            matchups = self.matchups
        live = self.last_live
        phase = self.phase

        mode = self._resolve_mode(settings, live, self.last_lcu)
        mode_label = MODES.get(mode, MODES["ranked"])[0]
        mode_api = MODES.get(mode, MODES["ranked"])[1]
        role = "6" if mode == "aram" else settings["role"]
        # En champ select manda la posición real del pick, no tu config.
        if mode != "aram" and self.last_lcu and self.last_lcu.get("position"):
            role = POSITION_ROLE.get(self.last_lcu["position"], role)

        champ = None
        champ_name = ""
        if live:
            champ = ddragon.champ_by_name(live.get("champion"))
            champ_name = live.get("champion") or ""
        elif self.last_lcu and self.last_lcu.get("champion_id"):
            champ = ddragon.champ_by_key(self.last_lcu["champion_id"])
            champ_name = champ["name"] if champ else ""
        elif self.last_lcu and self.last_lcu.get("hover_champion_id") and not self.last_lcu.get("locked"):
            champ = ddragon.champ_by_key(self.last_lcu["hover_champion_id"])
            champ_name = champ["name"] if champ else ""
        # Si la build cargada es de otro campeón (acabas de mover el ratón a
        # otro), no se muestran datos que no son del campeón actual.
        if overview and self.overview_champ and champ and self.overview_champ != champ["key"]:
            overview = None
        # Vista previa: el campeón está bajo el ratón, todavía sin fijar.
        champ_preview = bool(
            self.last_lcu
            and self.last_lcu.get("hover_champion_id")
            and not self.last_lcu.get("locked")
            and not live
        )

        state = {
            "status": "idle",
            "phase": phase,
            "mock": self.mock,
            "ready": ddragon.ready,
            "champ": None,
            "role": role,
            "role_label": ROLE_NAMES.get(role, role),
            "mode": mode,
            "mode_label": mode_label,
            "rank_label": RANK_NAMES.get(settings["rank"], settings["rank"]),
            "region_label": REGION_NAMES.get(settings["region"], settings["region"]),
            "settings": settings,
            "source": {"name": "U.GG", "patch": overview.get("patch") if overview else None},
            "stats": None,
            "runes": None,
            "spells": None,
            "skills": None,
            "items": None,
            "pet": None,
            "swap_verdict": None,
            "damage_vs_survival": None,
            "matchups": [],
            "live": None,
            "tips": [],
            "situations": [],
            "rune_advice": [],
            "needs": itemrules.needs_catalog() if ddragon.ready else [],
            "matchups_error": self.matchups_error,
            "enemies": [],
            "counter_plan": None,
            "champ_locked": bool(self.last_lcu.get("locked")) if self.last_lcu else False,
            "champ_preview": champ_preview,
            "my_runes": None,
            "my_spells": None,
            "rune_check": None,
            "rune_plan": None,
            "counter_core": None,
            "next_purchase": None,
            "game_phase": (self.last_lcu or {}).get("game_phase"),
        }

        # Tu estado real (leído del cliente de LoL), disponible incluso sin
        # datos de U.GG: runas, hechizos y fase de la partida.
        state["my_runes"] = self._my_runes_state(self.last_lcu)
        state["my_spells"] = self._my_spells_state(self.last_lcu)
        # El plan de runas depende de las opciones (endpoint "builds"), no del
        # overview: se calcula ya para que salga en cuanto haya opciones.
        enemy_champs_now = self._enemy_champs(live, self.last_lcu)
        me_is_ap_early = bool(champ and coach.champ_is_ap(champ.get("name")))
        builds_key = None
        if champ and champ.get("key"):
            builds_key = (
                champ["key"], mode_api, role, settings["rank"], settings["region"]
            )
            # Pide los datos de runas de este campeón en segundo plano (la
            # descarga de U.GG puede tardar o dar 403).
            self._want_rune_builds(champ["key"], settings, mode_api, role)
        rune_options = self._rune_options_state(enemy_champs_now, builds_key)
        if not rune_options and champ and champ.get("key"):
            rune_options = self._rune_options_live(
                champ, enemy_champs_now, settings, mode_api, role
            )
        state["rune_options"] = rune_options
        state["rune_plan"] = self._rune_plan_state(
            overview, rune_options, (self.last_lcu or {}).get("rune_page")
        )
        state["best_runes_now"] = self._best_runes_now_state(
            rune_options, (self.last_lcu or {}).get("rune_page"), enemy_champs_now, champ, me_is_ap_early
        )

        if champ:
            state["champ"] = {
                "name": champ["name"] if champ else champ_name,
                "id": champ["id"] if champ else champ_name,
                "key": champ["key"] if champ else None,
                "title": champ.get("title", "") if champ else "",
                "tags": champ.get("tags") or [],
            }
            state["status"] = "loading" if overview_loading and not overview else "ready"

        # Núcleo anti-counter y rivales: NO dependen del overview de U.GG. Se
        # calculan ya en champ select (con solo ver los rivales) y se actualizan
        # en vivo con los objetos reales, para ir por delante del counter.
        state["counter_core"] = self._counter_core_state(
            live, self.last_lcu, overview, champ, me_is_ap_early
        )
        state["enemies"] = self._enemies_state(
            live, settings, mode_api, me_is_ap_early
        )
        state["allies"] = self._allies_state(live, settings, mode_api)
        state["dmg_focus"] = self._dmg_focus_state(
            champ, enemy_champs_now, me_is_ap_early
        )

        if not overview:
            if state["status"] == "ready":
                state["status"] = "loading"
            state["tips"] = self._tips(state)
            return state

        state["status"] = "ready"
        state["source"]["patch"] = overview.get("patch")
        state["source"]["patch_stale"] = bool(overview.get("patch_stale"))
        state["source"]["current_patch"] = overview.get("current_patch")
        base_stats = champ.get("stats") if champ else None
        state["stats"] = {
            "winrate": round(overview["winrate"], 1) if overview.get("winrate") else None,
            "matches": overview.get("matches", 0),
            "core_matches": overview.get("core_matches", 0),
            "reliability": overview.get("reliability"),
            "low_sample": overview.get("low_sample", False)
            or (overview.get("reliability") == "baja"),
            "base": base_stats,
        }
        if base_stats:
            lvl = 1
            state["stats"]["level"] = lvl
            state["stats"]["current"] = {
                "hp": round(base_stats.get("hp", 0) + base_stats.get("hpperlevel", 0) * (lvl - 1)),
                "mp": round(base_stats.get("mp", 0) + base_stats.get("mpperlevel", 0) * (lvl - 1)),
                "armor": round(base_stats.get("armor", 0) + base_stats.get("armorperlevel", 0) * (lvl - 1), 2),
                "spellblock": round(base_stats.get("spellblock", 0) + base_stats.get("spellblockperlevel", 0) * (lvl - 1), 2),
                "attackdamage": round(base_stats.get("attackdamage", 0) + base_stats.get("attackdamageperlevel", 0) * (lvl - 1), 2),
                "attackspeed": round(base_stats.get("attackspeed", 0) * (1 + base_stats.get("attackspeedperlevel", 0) / 100 * (lvl - 1)), 3),
                "movespeed": base_stats.get("movespeed"),
            }
        state["runes"] = self._runes_state(overview)
        state["spells"] = self._spells_state(overview)
        state["skills"] = self._skills_state(overview, live)
        state["items"] = self._items_state(
            overview, live, settings, champ, enemy_champs_now, role
        )
        enemy_champs = self._enemy_champs(live, self.last_lcu)
        state["rune_check"] = self._rune_check(
            state["my_runes"], state["rune_options"], state.get("runes")
        )
        me_is_ap = bool(champ and coach.champ_is_ap(champ.get("name")))
        need_flags = coach.need_flags_from_counts(
            coach.analyze([{"champion": n} for n, _c in enemy_champs]),
            me_is_ap,
        )
        needs_ordered = [
            (k, need_flags[k][1]) for k in sorted(need_flags, key=lambda k: -need_flags[k][0])
        ] or [
            (b["need"], b["label"]) for b in (state["items"].get("needs") or [])[:1]
        ]
        state["swap_verdict"] = self._swap_verdict(
            state["items"].get("owned"),
            needs_ordered,
            (live or {}).get("gold", 0),
            (live or {}).get("level", 0),
            enemy_champs,
            me_is_ap,
        )
        me_prof = profiles.profile(champ["key"]) if champ else None
        enemy_profs = []
        live_roster = [
            p for p in ((live or {}).get("players") or [])
            if not p.get("mine") and not p.get("is_me")
        ] if self.phase == "in_game" else []
        for _name, enemy_champ in enemy_champs:
            prof = profiles.profile(enemy_champ["key"])
            if prof:
                # En partida: armadura/RM reales del rival (nivel + objetos
                # que ya compró). Se copia el perfil para no tocar la caché.
                for p in live_roster:
                    pc = ddragon.champ_by_name(p.get("champion"))
                    if pc and pc.get("key") == enemy_champ.get("key"):
                        arm, mrv = livemeta.live_resists(
                            enemy_champ, p.get("level"), p.get("items"))
                        prof = dict(prof, live_armor=arm, live_mr=mrv)
                        break
                enemy_profs.append(prof)
        live_items = None
        live_state = None
        if self.phase == "in_game" and live and live.get("players"):
            live_items = livemeta.analyze_items(live.get("players"))
            live_state = livemeta.analyze_game_state(live)
        state["live_meta"] = {
            "items": live_items,
            "game": live_state,
            "alerts": ((live_items or {}).get("alerts") or [])
            + ((live_state or {}).get("alerts") or []),
        }
        need_boost = {}
        if live_items or live_state:
            need_boost = livemeta.needs_boost(
                (live_items or {}).get("alerts"), (live_state or {}).get("alerts")
            )
        state["damage_vs_survival"] = itemrules.damage_vs_survival(
            overview.get("core_items"), me_prof, enemy_profs,
            (live or {}).get("level", 0) or 11,
            need_boost=need_boost,
        )
        try:
            state["hybrid_plan"] = hybrid.hybrid_plan(
                me_prof, enemy_profs, overview,
                owned_ids=list((live or {}).get("items") or []) if live else None,
                level=(live or {}).get("level", 0) or 18,
            )
        except Exception as e:
            _log(f"[advisor] hybrid falló: {e!r}")
            state["hybrid_plan"] = None
        try:
            state["first_buys"] = itemrules.first_buys(
                overview.get("core_items"), me_prof, enemy_profs,
                (live or {}).get("level", 0) or 11,
                state.get("damage_vs_survival"),
            )
        except Exception as e:
            _log(f"[advisor] first_buys falló: {e!r}")
            state["first_buys"] = None
        # Plan de counter: qué objeto concreto cambiar y por cuál, contra qué
        # rival. En partida se usa lo que llevas puesto; en champ select, el
        # núcleo de U.GG.
        try:
            owned_now = list(live.get("items") or []) if live else None
            state["counter_plan"] = counterplan.build_plan(
                champ.get("name") if champ else "",
                me_prof,
                enemy_profs,
                core_ids=overview.get("core_items") or [],
                owned_ids=owned_now,
                need_boost=need_boost,
                level=(live or {}).get("level", 0) or 11,
            )
        except Exception as e:
            print(f"[advisor] counter plan error: {e}")
            state["counter_plan"] = None
        state["next_purchase"] = self._next_purchase(
            state["counter_plan"], owned_now, (state.get("items") or {}).get("owned")
        )
        if champ:
            state["pet"] = recommend_pet(
                champ["name"], champ.get("key"), mode_api, overview, role,
                enemy_profs, me_prof,
            )
            if state["pet"] and state["pet"].get("id") and live:
                state["pet"]["owned"] = str(state["pet"]["id"]) in {
                    str(i) for i in live.get("items") or []
                }

        if self.phase == "in_game" and live:
            lvl_live = live.get("level", 0) or 1
            if base_stats:
                state["stats"]["level"] = lvl_live
                state["stats"]["current"] = {
                    "hp": round(base_stats.get("hp", 0) + base_stats.get("hpperlevel", 0) * (lvl_live - 1)),
                    "mp": round(base_stats.get("mp", 0) + base_stats.get("mpperlevel", 0) * (lvl_live - 1)),
                    "armor": round(base_stats.get("armor", 0) + base_stats.get("armorperlevel", 0) * (lvl_live - 1), 2),
                    "spellblock": round(base_stats.get("spellblock", 0) + base_stats.get("spellblockperlevel", 0) * (lvl_live - 1), 2),
                    "attackdamage": round(base_stats.get("attackdamage", 0) + base_stats.get("attackdamageperlevel", 0) * (lvl_live - 1), 2),
                    "attackspeed": round(base_stats.get("attackspeed", 0) * (1 + base_stats.get("attackspeedperlevel", 0) / 100 * (lvl_live - 1)), 3),
                    "movespeed": base_stats.get("movespeed"),
                }
            state["live"] = {
                "gold": live.get("gold", 0),
                "level": live.get("level", 0),
                "time": fmt_time(live.get("game_time", 0)),
                "kda": live.get("kda"),
                "items": live.get("items", []),
                "team_scores": live.get("team_scores"),
            }
            state["matchups"] = self._matchups_state(matchups, self._enemy_champs(live, self.last_lcu))
            state["situations"] = self._situations(live)
            state["counters"] = self._counters_state(live, overview)
            state["rune_advice"] = self._rune_advice(live)
            state["needs"] = self._needs(live, champ and champ["name"])
            state["enemies"] = self._enemies_state(
                live, settings, mode_api, coach.champ_is_ap(champ_name)
            )
            state["allies"] = self._allies_state(live, settings, mode_api)
        elif self.phase == "champ_select":
            state["matchups"] = self._matchups_state(matchups, self._enemy_champs(None, self.last_lcu))
            state["rune_advice"] = self._rune_advice(None)
            state["needs"] = self._needs(None, champ and champ["name"])
            state["enemies"] = self._enemies_state(
                None, settings, mode_api, coach.champ_is_ap(champ_name)
            )
            state["allies"] = self._allies_state(None, settings, mode_api)
        c = len(state.get("matchups") or [])
        if c != self._last_matchups_shown:
            self._last_matchups_shown = c
            _log(f"[advisor] rivales mostrables: {c} en fase {self.phase}")
        state["tips"] = self._tips(state)
        return state

    def _situations(self, live):
        players = live.get("players") or []
        foes = []
        for p in players:
            if p.get("mine"):
                continue
            foes.append({
                "champion": p.get("champion"),
                "items": p.get("items") or [],
            })
        player_ap = coach.champ_is_ap(live.get("champion") or "")
        return coach.situations(foes, player_ap)

    def _needs(self, live, champ_name):
        foes = []
        for p in ((live or {}).get("players") or []):
            if p.get("mine"):
                continue
            foes.append({"champion": p.get("champion"), "items": p.get("items") or []})
        if not foes:
            for name, _champ in self._enemy_champs(None, self.last_lcu):
                foes.append({"champion": name, "items": []})
        is_ap = coach.champ_is_ap(champ_name or "")
        return itemrules.prioritized_needs(coach.need_flags(foes, is_ap))

    def _want_enemy_build(self, champ_key, mode_api, settings):
        key = (champ_key, mode_api, settings["rank"], settings["region"])
        with self._lock:
            if key in self.enemy_builds or key in self.enemy_builds_loading:
                return
            self.enemy_builds_loading.add(key)

        def work():
            try:
                ov = ugg_client.get_overview(
                    champ_key, mode_api, "0", settings["rank"], settings["region"]
                )
            except Exception:
                ov = None
            with self._lock:
                self.enemy_builds[key] = ov
                self.enemy_builds_loading.discard(key)

        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _build_summary(ov):
        """Objetos (núcleo + tardíos) y runas reales de U.GG para un campeón."""
        if not ov:
            return {"items": [], "runes": [], "patch": None}
        items = []
        seen = set()
        for iid in ov.get("core_items") or []:
            if str(iid) in seen or str(iid) in CONSUMABLE_IDS:
                continue
            seen.add(str(iid))
            items.append({
                "id": int(iid),
                "name": ddragon.item_name(iid),
                "icon": f"/icon/item/{iid}.png",
                "price": ddragon.item_price(iid),
            })
        for options in ov.get("late_items") or []:
            for opt in options[:1]:
                iid = opt.get("id")
                if iid is None or str(iid) in seen or str(iid) in CONSUMABLE_IDS:
                    continue
                seen.add(str(iid))
                items.append({
                    "id": int(iid),
                    "name": ddragon.item_name(iid),
                    "icon": f"/icon/item/{iid}.png",
                    "price": ddragon.item_price(iid),
                    "winrate": round(opt["winrate"], 1) if opt.get("winrate") else None,
                })
            if len(items) >= 6:
                break
        runes = []
        for rid in (ov.get("runes") or {}).get("ids") or []:
            r = ddragon.rune(rid)
            if not r:
                continue
            runes.append({
                "id": int(rid),
                "name": r.get("name", str(rid)),
                "icon": f"/icon/rune/{rid}.png",
                "isStyle": bool(r.get("isStyle")),
            })
        return {"items": items[:6], "runes": runes, "patch": ov.get("patch")}

    def _enemy_build(self, champ_key, mode_api, settings):
        """Build típica del rival (núcleo + tardíos + runas) según U.GG, en caché."""
        key = (champ_key, mode_api, settings["rank"], settings["region"])
        with self._lock:
            ov = self.enemy_builds.get(key)
        return self._build_summary(ov)

    def _enemies_state(self, live, settings, mode_api, player_is_ap):
        """Por cada rival: sus objetos (reales en partida, o build U.GG en
        selección), sus runas, el objeto exacto para contrarrestarlo y el
        cambio concreto en tus 6 objetos si hace falta."""
        enemies = []
        owned = (live.get("items") or []) if live else []
        if live:
            for p in live.get("players") or []:
                if p.get("mine"):
                    continue
                c = ddragon.champ_by_name(p.get("champion"))
                if not c:
                    continue
                items = []
                for iid in p.get("items") or []:
                    if str(iid) in CONSUMABLE_IDS:
                        continue
                    items.append({
                        "id": int(iid),
                        "name": ddragon.item_name(iid),
                        "icon": f"/icon/item/{iid}.png",
                        "price": ddragon.item_price(iid),
                    })
                enemies.append({
                    "champion": c["name"],
                    "icon": f"/icon/champ/{c['key']}.png",
                    "items": items,
                    "runes": [],
                    "items_label": "Sus objetos ahora",
                    "counters": coach.counter_for_foe(c["name"], player_is_ap, p.get("items")),
                    "swap": coach.swap_for_foe(owned, c["name"], player_is_ap, p.get("items")),
                    "source": "en vivo",
                })
        if not enemies:
            for name, c in self._enemy_champs(None, self.last_lcu):
                b = self._enemy_build(c["key"], mode_api, settings)
                enemies.append({
                    "champion": c["name"],
                    "icon": f"/icon/champ/{c['key']}.png",
                    "items": b["items"],
                    "runes": b["runes"],
                    "items_label": "Build típica (U.GG)" if b["items"] else "Sin build en datos",
                    "counters": coach.counter_for_foe(c["name"], player_is_ap, []),
                    "swap": coach.swap_for_foe(owned, c["name"], player_is_ap, []),
                    "source": f"U.GG {b['patch']}" if b["items"] else "reglas",
                })
        return enemies

    def _best_runes_now_state(self, rune_options, rune_page, enemy_champs, champ, me_is_ap):
        if not rune_options:
            return None
        best = None
        for o in rune_options:
            if o.get("recommended"):
                best = o
                break
        if best is None:
            best = rune_options[0]
        cur = ""
        if rune_page and rune_page.get("primary_style_id"):
            cur = rune_page.get("primary_style_name") or rune_page.get("name") or ""
        prim = best.get("primary_es") or best.get("primary_style_name") or best.get("primary") or ""
        sec = best.get("secondary_es") or best.get("secondary_style_name") or best.get("secondary") or ""
        keystone = best.get("keystone_name") or ""
        if not keystone:
            for r in (best.get("runes") or best.get("perks") or []):
                if r.get("slot") == 0 or r.get("slot") == "kKeyStone":
                    keystone = r.get("name") or ""
                    break
        if not keystone and best.get("keystone"):
            k = ddragon.rune(best["keystone"])
            if k:
                keystone = k.get("name") or ""
        diff = ""
        if cur and prim and cur.lower() != prim.lower():
            diff = f"vs tu página: {cur} → cambiar a {prim}"
        elif cur and prim:
            diff = "Encaja bien con tu página actual"
        foes = ", ".join([n for n, _ in enemy_champs]) if enemy_champs else ""
        runes_list = []
        for r in (best.get("runes") or best.get("perks") or []):
            name = r.get("name") or ""
            if name:
                runes_list.append(name)
        if not runes_list and best.get("perks"):
            for r in best.get("perks") or []:
                n = ddragon.rune_name(r.get("id")) if r.get("id") else r.get("name")
                if n and n not in runes_list:
                    runes_list.append(n)
        return {
            "prim": prim,
            "sec": sec,
            "keystone": keystone,
            "runes": runes_list,
            "reason": best.get("why") or best.get("reason") or "Mejor por enfrentamiento directo ahora mismo",
            "diff": diff,
            "vs": foes,
            "source": best.get("source") or "U.GG",
            "recommended": True,
        }

    def _dmg_focus_state(self, champ, enemy_champs, me_is_ap):
        """Recomendación rápida AD/AP/híbrido según campeón + composición rival."""
        if not champ:
            return None
        tags = champ.get("tags") or []
        name = champ.get("name") or ""
        is_ap = bool(coach.champ_is_ap(name))
        ad = 0
        ap = 0
        for n, _c in enemy_champs:
            if coach.champ_is_ap(n):
                ap += 1
            else:
                ad += 1
        reason = []
        if is_ap and "Fighter" in tags:
            focus, label, cls = "ap", "Híbrido (AP + daño útil)", "mid"
        elif is_ap or "Mage" in tags:
            focus, label, cls = "ap", "AP", "ap"
        elif "Marksman" in tags or "Assassin" in tags and not is_ap:
            focus, label, cls = "ad", "AD", "ad"
        elif "Fighter" in tags or "Tank" in tags:
            if ad >= ap and not is_ap:
                focus, label, cls = "ad", "AD", "ad"
            else:
                focus, label, cls = "ad", "AD", "ad"
        else:
            focus, label, cls = "ad", "AD", "ad"
        if ap >= 2 and not is_ap:
            label = "Híbrido (AD + algo de AP)"
            reason.append("Rivales mayormente AP: conviene no ir 100% armadura pura")
        if ad >= 2 and is_ap:
            label = "Híbrido (AP + algo de AD)"
            reason.append("Rivales mayormente AD: no descartes objetos con defensas útiles")
        if not reason:
            reason.append("Señalado por tags del campeón + composición rival")
        return {
            "focus": focus,
            "label": label,
            "cls": cls,
            "reason": "; ".join(reason),
            "ad": ad,
            "ap": ap,
        }

    def _counter_core_state(self, live, lcu, overview, champ, me_is_ap):
        """Núcleo de objetos anti-counter, aparte de tu build funcional.

        Cuando el rival te counterea (apila AD, AP, curación, escudos, tanques,
        letalidad...), aquí sale QUÉ objetos comprar en bloque para ir por
        encima, y se recalcula en vivo con los objetos reales.

        - En partida: inventario REAL de cada rival (Live Client).
        - En champ select: composición rival (los objetos se proponen por
          reglas, sin inventar stats).

        Cada objeto se puntúa por cuántos rivales lo justifican: los que
        contestan a más amenazas van primero. No depende del overview de U.GG.
        """
        foes = []
        if live:
            for p in live.get("players") or []:
                if p.get("mine"):
                    continue
                foes.append({"champion": p.get("champion"), "items": p.get("items") or []})
        elif lcu:
            for name, _c in self._enemy_champs(None, lcu):
                foes.append({"champion": name, "items": []})
        if not foes:
            return None

        owned_ids = [int(i) for i in (live.get("items") or [])] if live else []
        owned_set = {str(i) for i in owned_ids}
        counts = coach.analyze(foes)

        # Votos por objeto: cuántos rivales distintos lo piden y por qué.
        votes = {}
        for f in foes:
            name = f.get("champion")
            seen_for_foe = set()
            for e in coach.counter_for_foe(name, me_is_ap, f.get("items")):
                iid = e.get("id")
                if not iid or iid in seen_for_foe:
                    continue
                seen_for_foe.add(iid)
                v = votes.setdefault(str(iid), {
                    "item": e, "foes": [], "cats": set(), "score": 0,
                })
                v["foes"].append(name)
                if e.get("cat"):
                    v["cats"].add(e["cat"])
                v["score"] += 1

        if not votes:
            return None

        blocks = []
        for iid, v in votes.items():
            e = v["item"]
            eff = e.get("efficiency") or {}
            blocks.append({
                "id": iid,
                "name": ddragon.item_name(iid),
                "icon": f"/icon/item/{iid}.png",
                "price": ddragon.item_price(iid),
                "desc": ddragon.item_plaintext(iid),
                "reason": e.get("reason") or "",
                "cats": sorted(v["cats"]),
                "foes": sorted(set(v["foes"])),
                "score": v["score"],
                "efficiency": eff.get("ratio"),
                "owned": str(iid) in owned_set,
            })
        # Prioridad: contesta a más rivales, luego mejor eficiencia de oro,
        # luego el que aún no tienes.
        blocks.sort(key=lambda b: (-b["score"], -(b["efficiency"] or 0), b["owned"]))
        blocks = blocks[:6]
        return {
            "blocks": blocks,
            "counts": counts,
            "num_faltan": sum(1 for b in blocks if not b["owned"]),
            "en_partida": bool(owned_ids),
            "source": "objetos reales del rival (en vivo)" if live
            else "composición rival (reglas, sin winrate)",
        }

    def _allies_state(self, live, settings, mode_api):
        """Por cada aliado: sus objetos (reales o build U.GG) y sus runas."""
        allies = []
        if live:
            for p in live.get("players") or []:
                if not p.get("mine") or p.get("is_me"):
                    continue
                c = ddragon.champ_by_name(p.get("champion"))
                if not c:
                    continue
                items = []
                for iid in p.get("items") or []:
                    if str(iid) in CONSUMABLE_IDS:
                        continue
                    items.append({
                        "id": int(iid),
                        "name": ddragon.item_name(iid),
                        "icon": f"/icon/item/{iid}.png",
                        "price": ddragon.item_price(iid),
                    })
                allies.append({
                    "champion": c["name"],
                    "icon": f"/icon/champ/{c['key']}.png",
                    "items": items,
                    "runes": [],
                    "items_label": "Sus objetos ahora",
                    "source": "en vivo",
                })
        if not allies:
            for name, c in self._allies_champs(None, self.last_lcu):
                b = self._enemy_build(c["key"], mode_api, settings)
                allies.append({
                    "champion": c["name"],
                    "icon": f"/icon/champ/{c['key']}.png",
                    "items": b["items"],
                    "runes": b["runes"],
                    "items_label": "Build típica (U.GG)" if b["items"] else "Sin datos",
                    "source": f"U.GG {b['patch']}" if b["items"] else "reglas",
                })
        return allies

    def _rune_advice(self, live):
        foes = []
        if live:
            for p in (live.get("players") or []):
                if p.get("mine"):
                    continue
                foes.append({"champion": p.get("champion"), "items": p.get("items") or []})
        else:
            for name, _champ in self._enemy_champs(None, self.last_lcu):
                foes.append({"champion": name, "items": []})
        return coach.rune_advice(foes)

    def _counters_state(self, live, overview):
        owned_ids = live.get("items") or []
        foes = []
        for p in (live.get("players") or []):
            if p.get("mine"):
                continue
            foes.append({"champion": p.get("champion"), "items": p.get("items") or []})
        player_ap = coach.champ_is_ap(live.get("champion") or "")
        wr_map = {}
        for options in (overview.get("late_items") or []):
            for opt in options:
                if opt.get("winrate"):
                    wr_map[str(opt.get("id"))] = opt["winrate"]
        owned_items = []
        for iid in owned_ids:
            wr = wr_map.get(str(iid))
            owned_items.append({
                "id": int(iid),
                "name": ddragon.item_name(iid),
                "icon": f"/icon/item/{iid}.png",
                "winrate": round(wr, 1) if wr else None,
                "defense": coach.defense_profile(int(iid)),
            })
        swaps = coach.counter_swaps(owned_ids, foes, player_ap)
        for s in swaps:
            if s.get("swap"):
                s["swap_name"] = ddragon.item_name(s["swap"])
                s["swap_icon"] = f"/icon/item/{s['swap']}.png"
            if s.get("have") is not None:
                s["have_name"] = ddragon.item_name(s["have"])
                s["have_icon"] = f"/icon/item/{s['have']}.png"
        return {"owned_items": owned_items, "swaps": swaps}

    def _runes_state(self, overview):
        runes = overview.get("runes") or {}
        ids = runes.get("ids") or []
        primary_style = ddragon.rune(runes.get("primary"))
        secondary_style = ddragon.rune(runes.get("secondary"))
        primary_name = primary_style.get("name") if primary_style else ""
        secondary_name = secondary_style.get("name") if secondary_style else ""
        resolved = []
        for rid in ids:
            r = ddragon.rune(rid)
            if not r:
                continue
            resolved.append({
                "id": rid,
                "name": r.get("name", str(rid)),
                "icon": f"/icon/rune/{rid}.png",
                "style": r.get("style", ""),
                "slot": r.get("slot", 0),
            })
        main = sorted(
            (x for x in resolved if x["style"] == primary_name),
            key=lambda x: x["slot"],
        )
        sec = sorted(
            (x for x in resolved if x["style"] == secondary_name),
            key=lambda x: x["slot"],
        )
        shards = []
        for sid in overview.get("shards") or []:
            shards.append({
                "id": sid,
                "name": ddragon.shard_name(sid),
                "icon": f"/icon/shard/{sid}.png",
            })
        return {
            "primary_style": primary_name,
            "secondary_style": secondary_name,
            "primary": main,
            "secondary": sec,
            "list": resolved,
            "shards": shards,
            "winrate": runes.get("winrate"),
        }

    def _want_rune_builds(self, champ_key, settings, mode_api, role):
        """Pide las alternativas de runas reales (endpoint builds de U.GG)."""
        key = (champ_key, mode_api, role, settings["rank"], settings["region"])
        if self.rune_builds_key == key and self.rune_builds is not None:
            return
        if self.rune_builds_loading and self.rune_builds_key == key:
            return
        self.rune_builds_loading = True
        self.rune_builds_key = key

        def work():
            try:
                data = ugg_client.get_rune_builds(
                    champ_key, mode_api, role, settings["rank"], settings["region"]
                )
                with self._lock:
                    if data:
                        self.rune_builds = data
                        # Se guarda con qué clave se descargó: si el jugador
                        # pasa el ratón por otro campeón, los datos viejos no
                        # se pueden reutilizar.
                        self.rune_builds_for = key
                    self.rune_builds_loading = False
            except Exception as e:
                print(f"[advisor] rune builds error: {e}")
                with self._lock:
                    self.rune_builds_loading = False

        threading.Thread(target=work, daemon=True).start()

    def _rune_metrics(self, enemy_champs, champ=None):
        """Métricas de la composición rival para cruzar con las runas."""
        try:
            return coach.analyze([{"champion": n} for n, _c in enemy_champs]) or {}
        except Exception:
            return {}

    def _rune_options_live(self, champ, enemy_champs, settings, mode_api, role):
        """Opciones de runas calculadas al vuelo, con caché propia.

        Se usa cuando el endpoint "builds" aún no ha llegado (o falla): así el
        overlay puede enseñar las mejores runas desde el primer momento. La
        descarga va en segundo plano para no bloquear el poll del overlay, y
        tiene TTL para no castigar a U.GG en cada iteración.
        """
        key = (
            champ.get("key"),
            mode_api,
            role,
            settings.get("rank"),
            settings.get("region"),
            tuple(sorted(n for n, _c in enemy_champs)),
        )
        now = time.time()
        if self._rune_opts_key == key and self._rune_opts_cache is not None:
            if (now - self._rune_opts_at) < RUNE_OPTS_TTL:
                return self._rune_opts_cache
        if not self._rune_opts_loading:
            self._rune_opts_loading = True

            def work():
                try:
                    opts = runeoptions.fetch_options(
                        champ.get("key"),
                        mode_api,
                        role,
                        settings.get("rank"),
                        settings.get("region"),
                        metrics=self._rune_metrics(enemy_champs, champ),
                        my_tags=champ.get("tags") or [],
                    )
                    if opts:
                        with self._lock:
                            self._rune_opts_key = key
                            self._rune_opts_cache = opts
                            self._rune_opts_at = time.time()
                except Exception:
                    pass
                finally:
                    with self._lock:
                        self._rune_opts_loading = False

            threading.Thread(target=work, daemon=True).start()
        # Sin datos nuevos todavía: reusar lo cacheado aunque sea viejo.
        if self._rune_opts_cache is not None:
            return self._rune_opts_cache
        return []

    def _rune_options_state(self, enemy_champs, key=None):
        """Opciones de runas con datos reales, y cuál encaja mejor con el rival.

        Sale del endpoint "builds" de U.GG: cada opción es una página de runas
        real con sus partidas y su winrate. La recomendación no es "la más
        usada" a ciegas: se cruza con lo que hace el equipo enemigo.
        """
        builds = self.rune_builds
        if not builds:
            return []
        if key is not None and getattr(self, "rune_builds_for", None) != key:
            # Los datos son de otro campeón/rol: no sirven.
            return []
        metrics = {}
        try:
            analysis = coach.analyze([{"champion": n} for n, _c in enemy_champs])
            metrics = analysis or {}
        except Exception:
            metrics = {}
        my_tags = []
        try:
            champ = ddragon.champ_by_key(self.last_champ_key) if self.last_champ_key else None
            my_tags = (champ or {}).get("tags") or []
        except Exception:
            my_tags = []

        return runeoptions.build_options(builds, metrics, my_tags)

    def _rune_plan_state(self, overview, rune_options, page):
        """El plan de runas en el orden del cliente y el diff con la página
        que se está editando ahora mismo.

        Se construye SIEMPRE que haya una opción recomendada de U.GG, para que
        se vea desde antes de entrar a partida / antes de tocar la página.
        """
        if not rune_options:
            return None
        best = None
        for o in rune_options:
            if o.get("recommended"):
                best = o
                break
        if best is None:
            # Si no hay "recommended" explícito, coger la mejor por muestra/ventaja
            best = rune_options[0]
        shards = (overview or {}).get("shards") or best.get("shards") or []
        try:
            plan = runeoptions.build_plan(best, shards, page)
        except Exception as e:
            print(f"[advisor] rune plan error: {e}")
            return None
        if not plan:
            return None
        if page:
            plan["editing"] = True
            plan["editing_name"] = page.get("name")
        else:
            plan["editing"] = False
            plan["editing_name"] = None
        return plan

    def _next_purchase(self, plan, owned_now, owned_state):
        """La siguiente compra que el plan de counter te pide hacer ahora.

        Prioridad: botas (si hay cambio), luego el cambio de mayor prioridad
        cuyo objeto de entrada todavía no llevas puesto.
        """
        if not plan:
            return None
        owned = {str(i) for i in (owned_now or owned_state or [])}
        candidates = []
        botas = plan.get("botas") or {}
        if botas.get("take"):
            candidates.append({
                "item": botas["take"],
                "why": botas.get("why") or "Estas botas encajan mejor con el daño rival.",
                "kind": "botas",
                "out": botas.get("have"),
                "priority": 1000,
            })
        for c in plan.get("cambios") or []:
            item = c.get("in")
            if not item:
                continue
            candidates.append({
                "item": item,
                "why": c.get("why") or "",
                "kind": "cambio",
                "out": c.get("out"),
                "need_label": c.get("need_label"),
                "contra": c.get("contra") or [],
                "priority": c.get("priority") or 0,
            })
        candidates.sort(key=lambda x: -x["priority"])
        for cand in candidates:
            item_id = str((cand.get("item") or {}).get("id"))
            if item_id and item_id in owned:
                continue
            return cand
        return None

    def _spells_state(self, overview):
        out = []
        for sid in (overview.get("spells") or {}).get("ids") or []:
            s = ddragon.spell(sid)
            out.append({
                "id": sid,
                "name": s["name"] if s else f"Spell {sid}",
                "icon": f"/icon/spell/{sid}.png",
            })
        return out

    def _my_runes_state(self, lcu):
        """Tus runas REALES (leídas del cliente de LoL), no una suposición."""
        raw = (lcu or {}).get("runes") or {}
        if not raw:
            return None
        out = {"source": raw.get("source") or "cliente de LoL", "perks": [], "keystone": None}
        if raw.get("ids"):
            # En champ select solo vienen los IDs: se resuelven con el catálogo.
            ids = [int(i) for i in raw["ids"]]
            out["perks"] = [p for p in (self._rune_entry(i) for i in ids) if p]
            for p in out["perks"]:
                if p.get("slot") == 0:
                    out["keystone"] = p
                    break
            if not out["keystone"]:
                for p in out["perks"]:
                    if not p.get("shard") and p.get("slot") == 0:
                        out["keystone"] = p
                        break
            out["keystone"] = out["keystone"] or (out["perks"][0] if out["perks"] else None)
            return out
        for p in raw.get("perks") or []:
            pid = p.get("id")
            entry = {
                "id": pid,
                "name": p.get("name") or "",
                "slot": p.get("slot") or "",
                "icon": f"/icon/rune/{pid}.png",
                "shard": ddragon.is_shard(pid),
            }
            if not entry["name"]:
                cat = self._rune_entry(pid)
                if cat:
                    entry["name"] = cat["name"]
                    entry["shard"] = cat.get("shard", False)
            out["perks"].append(entry)
        keystone = raw.get("keystone")
        if keystone:
            kid = keystone.get("id")
            out["keystone"] = {
                "id": kid,
                "name": keystone.get("name") or (self._rune_entry(kid) or {}).get("name") or "",
                "icon": f"/icon/rune/{kid}.png",
            }
        elif out["perks"]:
            out["keystone"] = out["perks"][0]
        out["page_name"] = raw.get("page_name")
        out["primary_style_name"] = raw.get("primary_style_name")
        return out

    def _rune_entry(self, rune_id):
        r = ddragon.rune(rune_id)
        if r:
            return {
                "id": int(rune_id),
                "name": r.get("name", str(rune_id)),
                "icon": f"/icon/rune/{rune_id}.png",
                "slot": r.get("slot"),
                "style": r.get("style"),
                "shard": False,
            }
        if ddragon.is_shard(rune_id):
            return {
                "id": int(rune_id),
                "name": ddragon.shard_name(rune_id),
                "icon": f"/icon/rune/{rune_id}.png",
                "slot": 6,
                "style": "",
                "shard": True,
            }
        return None

    def _my_spells_state(self, lcu):
        """Tus hechizos REALES (los que llevas en la partida)."""
        ids = (lcu or {}).get("spells") or []
        out = []
        for sid in ids:
            s = ddragon.spell(sid)
            out.append({
                "id": int(sid),
                "name": SPELL_NAMES_ES.get(int(sid)) or (s or {}).get("name") or f"Spell {sid}",
                "icon": f"/icon/spell/{sid}.png",
            })
        return out or None

    def _rune_check(self, my_runes, rune_options, ugg_runes=None):
        """Veredicto: ¿la runa que llevas es la que pide esta partida?"""
        if not my_runes:
            return None
        keystone = (my_runes.get("keystone") or {}).get("name")
        if not keystone:
            return None
        options = rune_options or []
        for opt in options:
            if (opt.get("keystone_name") or "").lower() == keystone.lower():
                return {
                    "keystone": keystone,
                    "verdict": "ok",
                    "texto": f"Llevas {keystone}: es la keystone que mejor encaja contra esta composición.",
                }
        # Sin alternativas de U.GG: se compara con la keystone de tu build.
        ref = None
        ugg_keystone = None
        for p in ((ugg_runes or {}).get("primary") or []):
            if p.get("slot") == 0:
                ugg_keystone = p
                break
        if ugg_keystone:
            ref = ugg_keystone.get("name")
            if (ref or "").lower() == keystone.lower():
                return {
                    "keystone": keystone,
                    "verdict": "ok",
                    "texto": f"Llevas {keystone}: es la keystone de la build de tu rol.",
                }
        alt = None
        for opt in options:
            if opt.get("recommended") and opt.get("keystone_name"):
                alt = opt
                break
        if not alt and ugg_keystone:
            alt = {
                "keystone_name": ugg_keystone.get("name"),
                "keystone_icon": ugg_keystone.get("icon"),
                "why": "la keystone más usada en tu rol",
            }
        if not alt or not alt.get("keystone_name"):
            return {"keystone": keystone, "verdict": "sin_datos", "texto": f"Llevas {keystone}."}
        return {
            "keystone": keystone,
            "verdict": "cambia",
            "texto": f"Llevas {keystone}; contra esta composición te convence más {alt['keystone_name']}.",
            "recomendada": {
                "keystone": alt.get("keystone_name"),
                "icon": alt.get("keystone_icon"),
                "why": alt.get("why"),
            },
        }

    def _skills_state(self, overview, live):
        skills = overview.get("skills") or {}
        order = skills.get("order") or []
        current = {"Q": 0, "W": 0, "E": 0, "R": 0}
        total = 0
        if live:
            for k in current:
                v = (live.get("abilities") or {}).get(k, 0)
                if v:
                    current[k] = int(v)
                total += current[k]
        nxt = None
        if order and total < len(order):
            nxt = order[total]
        return {
            "order": order,
            "max": skills.get("max", ""),
            "current": current,
            "next": nxt,
            "points_spent": total,
        }

    def _items_state(self, overview, live, settings, champ=None, enemy_champs=None, role=None):
        owned = set()
        gold = 0
        game_time = 0
        if live:
            owned = {str(i) for i in live.get("items") or []}
            gold = live.get("gold", 0)
            game_time = live.get("game_time", 0)

        def item_info(iid, wr=None):
            return {
                "id": int(iid),
                "name": ddragon.item_name(iid),
                "icon": f"/icon/item/{iid}.png",
                "price": ddragon.item_price(iid),
                "desc": ddragon.item_plaintext(iid),
                "owned": str(iid) in owned,
                "winrate": round(wr, 1) if wr else None,
                "efficiency": goldeff.item_efficiency(iid),
            }

        starting = [item_info(i) for i in overview.get("starting_items") or []]
        core = [item_info(i) for i in overview.get("core_items") or []]
        late = []
        for idx, options in enumerate(overview.get("late_items") or []):
            for opt in options:
                late.append(item_info(opt["id"], opt.get("winrate")))

        plan = []
        if game_time < 360:
            plan.extend([i["id"] for i in starting if i["id"] not in CONSUMABLE_IDS])
        plan.extend([i["id"] for i in core])
        plan.extend([i["id"] for i in late])

        seen = set()
        ordered_plan = []
        for iid in plan:
            s = str(iid)
            if s in seen or s in CONSUMABLE_IDS:
                continue
            seen.add(s)
            ordered_plan.append(iid)

        # Build completa de 6 espacios: núcleo + mejores tardíos (por winrate)
        full = []
        seen_full = set()
        for i in core:
            if i["id"] not in seen_full and str(i["id"]) not in CONSUMABLE_IDS:
                full.append(i)
                seen_full.add(i["id"])
        late_by_wr = sorted(
            [x for x in late if x["id"] not in seen_full and str(x["id"]) not in CONSUMABLE_IDS],
            key=lambda x: -(x.get("winrate") or 0),
        )
        for i in late_by_wr:
            if len(full) >= 6:
                break
            full.append(i)
            seen_full.add(i["id"])
        full = full[:6]

        target = None
        for iid in ordered_plan:
            if str(iid) not in owned:
                target = iid
                break

        affordables = []
        missing_gold = 0
        complete_now = False
        target_state = None
        if target is not None:
            components = ddragon.item_full_tree(target)
            owned_components = [c for c in components if c in owned]
            value_owned = sum(ddragon.item_price(c) for c in owned_components)
            total_price = ddragon.item_price(target)
            remaining = max(0, total_price - value_owned)
            complete_now = gold >= remaining
            missing_gold = max(0, int(remaining - gold))
            not_owned_components = [c for c in components if c not in owned]
            for c in sorted(not_owned_components, key=lambda x: -ddragon.item_price(x)):
                price = ddragon.item_price(c)
                if 0 < price <= gold:
                    affordables.append({
                        "id": int(c),
                        "name": ddragon.item_name(c),
                        "icon": f"/icon/item/{c}.png",
                        "price": price,
                        "desc": ddragon.item_plaintext(c),
                    })
            affordables = affordables[:3]
            target_state = item_info(target)
            target_state["remaining"] = remaining
            target_state["complete_now"] = complete_now
            target_state["missing_gold"] = missing_gold
            target_state["owned_components"] = [
                {"id": int(c), "name": ddragon.item_name(c), "icon": f"/icon/item/{c}.png"}
                for c in owned_components
            ]

        champ_name = (champ or {}).get("name") or ""
        champ_tags = set(ddragon.champ_tags(champ_name)) if champ_name else set()
        is_ap = bool(champ_name and coach.champ_is_ap(champ_name))
        if is_ap and "Mage" not in champ_tags and champ_tags & {"Tank", "Support"}:
            is_ap = False
        if is_ap:
            natural_kind = "ap"
        elif champ_tags & {"Marksman", "Fighter", "Assassin"}:
            natural_kind = "ad"
        else:
            natural_kind = None
        pool_ids = [i["id"] for i in core] + [x["id"] for x in late]
        alt_builds = []
        for kind in ("ad", "ap"):
            build = itemrules.full_damage_build(
                kind, champ_tags, pool_ids, (live or {}).get("level", 0) or 11
            )
            natural = kind == natural_kind
            build["natural"] = natural
            if natural:
                build["note"] = (
                    f"Tu campeón escala con {kind.upper()}: es la versión de máximo daño."
                )
            elif natural_kind:
                build["note"] = (
                    f"Tu campeón escala con {natural_kind.upper()}; esta full {kind.upper()} "
                    f"es experimental: las piezas son reales, pero no aprovechan sus ratios."
                )
            else:
                build["note"] = (
                    f"Tu campeón no es de daño puro: esta full {kind.upper()} es "
                    f"experimental (piezas reales, sin winrate)."
                )
            alt_builds.append(build)
        alt_builds.sort(key=lambda b: not b["natural"])

        enemy_counts = coach.analyze(
            [{"champion": name} for name, _count in (enemy_champs or [])]
        )
        ctx = archetypes.context_from_champ(
            champ, role, enemy_counts, live, is_ap
        )
        extra_builds = archetypes.build_archetypes(
            champ_tags, is_ap, role, pool_ids,
            (live or {}).get("level", 0) or 11, ctx,
        )

        return {
            "target": target_state,
            "affordable": affordables,
            "complete_now": complete_now,
            "gold": int(gold),
            "full": full,
            "alt_builds": alt_builds,
            "archetypes": extra_builds,
            "stages": [
                {"label": "Inicio", "items": starting},
                {"label": "Núcleo", "items": core},
                {"label": "Tardíos", "items": late},
            ],
            "needs": itemrules.needs_catalog(),
            "owned": sorted(owned),
        }

    @staticmethod
    def _swap_verdict(owned_ids, needs, gold, level, enemy_champs, is_ap=False):
        """Cambio de objeto concreto: "quita X, pon Y" + por qué (regla, sin winrate).

        Traduce las necesidades de tu composición rival a un objeto REAL y
        terminado, y elige cuál de TUS objetos quitar usando la eficiencia de oro
        (el más flojo). En el draft (sin inventario) propone un hueco libre."""
        if not needs:
            return None
        owned = [int(i) for i in (owned_ids or []) if str(i) not in CONSUMABLE_IDS]
        damage = "ap" if is_ap else "ad"
        offensive = {"pen_armadura", "pen_magica", "dano_fisico", "poder_habilidad", "critico", "corta_curas"}
        score = 0
        pick = None
        pick_reason = ""
        for need, reason in needs:
            if need in offensive:
                opt = itemrules.best_option(need, exclude=owned, damage=damage)
            else:
                opt = itemrules.best_defensive_option(need, damage, exclude=owned)
            if not opt:
                continue
            s = itemrules.NEED_PRIORITY.get(need, 0)
            if s > score:
                score, pick, pick_reason = s, opt, reason
        if not pick:
            return None

        def entry(info):
            if not info:
                return None
            return {
                "id": info["id"],
                "name": info["name"],
                "icon": info.get("icon") or f"/icon/item/{info['id']}.png",
                "price": info.get("price"),
                "desc": info.get("desc"),
                "categories": info.get("categories"),
                "category_labels": info.get("category_labels"),
                "efficiency": info.get("efficiency"),
            }

        take = entry(pick)
        if owned:
            candidates = []
            for iid in owned:
                if itemrules.is_boots(iid):
                    continue
                info = itemrules.item_info(iid)
                if not info:
                    continue
                eff = (info.get("efficiency") or {}).get("ratio")
                candidates.append((eff if eff is not None else 1.0, iid, info))
            if candidates:
                candidates.sort(key=lambda c: c[0])
                weakest = candidates[0]
                have = entry(weakest[2])
                return {
                    "mode": "swap",
                    "have": have,
                    "take": take,
                    "missing": 0,
                    "why": (
                        f"Contra esta composición te falta {take['name']}: "
                        f"{pick_reason}. Quita {have['name']} (el que menos te aporta) "
                        f"y pon {take['name']}."
                    ),
                    "source": "regla (sin winrate)",
                }
        # Sin inventario (draft): hueco libre y oro que falta.
        total_gold = pick.get("price") or 0
        own_gold = sum(ddragon.item_price(i) for i in owned)
        missing = max(0, total_gold - max(0, (gold or 0)))
        return {
            "mode": "add",
            "have": None,
            "take": take,
            "missing": int(missing),
            "why": (
                f"Contra esta composición te falta {take['name']}: {pick_reason}."
            ),
            "source": "regla (sin winrate)",
        }

    @staticmethod
    def _enemy_champs(live, lcu):
        out = []
        seen = set()
        if live:
            for p in live.get("players") or []:
                if p.get("mine"):
                    continue
                champ = ddragon.champ_by_name(p.get("champion"))
                if champ and champ["name"] not in seen:
                    seen.add(champ["name"])
                    out.append((p.get("champion"), champ))
        if not out and lcu:
            for cid in lcu.get("enemies") or []:
                champ = ddragon.champ_by_key(str(cid))
                if champ and champ["name"] not in seen:
                    seen.add(champ["name"])
                    out.append((champ["name"], champ))
        return out

    @staticmethod
    def _allies_champs(live, lcu):
        out = []
        seen = set()
        if live:
            for p in live.get("players") or []:
                if not p.get("mine") or p.get("is_me"):
                    continue
                champ = ddragon.champ_by_name(p.get("champion"))
                if champ and champ["name"] not in seen:
                    seen.add(champ["name"])
                    out.append((p.get("champion"), champ))
        if not out and lcu:
            for cid in lcu.get("allies") or []:
                champ = ddragon.champ_by_key(str(cid))
                if champ and champ["name"] not in seen:
                    seen.add(champ["name"])
                    out.append((champ["name"], champ))
        return out

    def _matchups_state(self, matchups, enemy_champs):
        if not matchups:
            return []
        by_id = {m["champion_id"]: m for m in matchups}
        out = []
        for disp_name, champ in enemy_champs:
            m = by_id.get(int(champ["key"]))
            if m:
                out.append({
                    "champion": champ["name"],
                    "icon": f"/icon/champ/{champ['key']}.png",
                    "winrate": round(m["winrate"], 1),
                    "matches": m["matches"],
                    "favorable": m["winrate"] >= 50,
                })
            else:
                out.append({
                    "champion": champ["name"],
                    "icon": f"/icon/champ/{champ['key']}.png",
                    "winrate": None,
                    "matches": None,
                    "favorable": False,
                    "no_data": True,
                })
        out.sort(key=lambda x: (x["winrate"] is None, x["winrate"]))
        tag = "|".join(champ["name"] for _, champ in enemy_champs) + "=>" + "|".join(x["champion"] for x in out)
        if tag != self._last_mu_tag:
            self._last_mu_tag = tag
            _log(f"[advisor] rivales detectados ({len(enemy_champs)}): {tag}")
        return out

    def _tips(self, state):
        tips = []
        items = state.get("items") or {}
        skills = state.get("skills") or {}
        if state.get("phase") == "in_game":
            target = items.get("target")
            if target and items.get("complete_now"):
                tips.append({
                    "type": "buy",
                    "text": f"¡Compra {target['name']} ahora! ({target['price']}g)",
                })
            elif target and items.get("affordable"):
                first = items["affordable"][0]
                if first["price"] <= items.get("gold", 0) and not first.get("owned"):
                    tips.append({
                        "type": "buy",
                        "text": f"Compra {first['name']} ({first['price']}g) hacia {target['name']}",
                    })
            elif target:
                tips.append({
                    "type": "gold",
                    "text": f"Faltan {target.get('missing_gold', 0)}g para {target['name']}",
                })
            if skills.get("next"):
                lvl = skills["current"].get(skills["next"], 0) + 1
                tips.append({
                    "type": "skill",
                    "text": f"Sube {skills['next']} (nivel {lvl})",
                })
            for s in (state.get("situations") or [])[:1]:
                item = s["items"][0]
                tips.append({
                    "type": "counter",
                    "text": (
                        f"Contra {s['label']}: {item['name']} ({item['price']}g) "
                        f"— {coach.WHY_SHORT.get(s['key'], s['key'])}"
                    ),
                })
        for m in (state.get("matchups") or [])[:1]:
            if not m["favorable"]:
                tips.append({
                    "type": "danger",
                    "text": f"Cuidado con {m['champion']}: ganas solo {m['winrate']}%",
                })
        return tips


advisor = Advisor()
