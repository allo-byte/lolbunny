import base64
import os
import threading
import time

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LOCKFILE_CANDIDATES = [
    r"C:\Riot Games\League of Legends\lockfile",
    os.path.join(os.environ.get("LOCALAPPDATA", ""), r"Riot Games\League of Legends\lockfile"),
    os.path.join(os.environ.get("PROGRAMFILES", ""), r"Riot Games\League of Legends\lockfile"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", ""), r"Riot Games\League of Legends\lockfile"),
]


class LCUClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._session = requests.Session()
        self._session.verify = False
        self._cache = {"available": False, "champion_id": None, "phase": None, "enemies": [], "allies": []}
        # Las páginas de runas y el gameflow cambian muy despacio: se
        # releen cada pocos segundos para no castigar al cliente de Riot.
        self._pages_cache = {"at": 0.0, "data": None}
        self._flow_cache = {"at": 0.0, "data": None}
        self._page_cache = {"at": 0.0, "data": None}

    def _find_lockfile(self, custom=None):
        paths = []
        if custom:
            paths.append(custom)
        paths.extend(LOCKFILE_CANDIDATES)
        for p in paths:
            if p and os.path.exists(p):
                return p
        return None

    def _read_lockfile(self, path):
        with open(path, "r", encoding="utf8", errors="ignore") as f:
            parts = f.read().strip().split(":")
        if len(parts) < 5:
            return None
        name, pid, port, password, protocol = parts[:5]
        return {"port": int(port), "password": password, "protocol": protocol.lower()}

    def _get(self, lock, endpoint):
        auth = base64.b64encode(f"riot:{lock['password']}".encode()).decode()
        scheme = "https" if lock["protocol"] == "https" else "http"
        url = f"{scheme}://127.0.0.1:{lock['port']}{endpoint}"
        r = self._session.get(
            url,
            headers={"Authorization": f"Basic {auth}"},
            timeout=1.0,
        )
        if r.status_code != 200:
            return None
        return r.json()

    def _queue_id(self, lock):
        for endpoint in ("/lol-gameflow/v1/session", "/lol-champ-select/v1/session"):
            data = self._get(lock, endpoint)
            if not isinstance(data, dict):
                continue
            gd = data.get("gameData") or {}
            q = gd.get("queue") or {}
            qid = q.get("id")
            if qid:
                try:
                    return int(qid)
                except Exception:
                    pass
        return None

    # ---------- runas y hechizos reales (lo que llevas puesto) ----------

    def _rune_pages(self, lock):
        """Páginas de runas del cliente (con la que está activa).

        Solo se relee cada 10 s: cambia muy pocas veces y cada llamada al
        cliente de Riot tiene coste.
        """
        now = time.time()
        with self._lock:
            if now - self._pages_cache["at"] < 10.0 and self._pages_cache["data"] is not None:
                return self._pages_cache["data"]
        data = self._get(lock, "/lol-perks/v1/pages")
        if not isinstance(data, list):
            return None
        with self._lock:
            self._pages_cache = {"at": now, "data": data}
        return data

    @staticmethod
    def _iter_actions(session):
        """Aplana las acciones del champ select.

        El cliente real devuelve "actions" como lista de fases y cada fase es
        una lista de acciones: [[{...}, {...}], [{...}]]. Se aceptan también
        la forma de diccionarios por fase para no romper con datos viejos.
        """
        out = []
        for phase in session.get("actions") or []:
            if isinstance(phase, list):
                out.extend([a for a in phase if isinstance(a, dict)])
            elif isinstance(phase, dict):
                inner = phase.get("actions")
                if isinstance(inner, list):
                    out.extend([a for a in inner if isinstance(a, dict)])
                else:
                    out.append(phase)
        return out

    @staticmethod
    def _norm_position(pos):
        pos = str(pos or "").strip().upper()
        if pos in ("MIDDLE", "MID"):
            return "MID"
        if pos in ("BOTTOM", "BOT"):
            return "BOTTOM"
        if pos in ("TOP", "JUNGLE", "SUPPORT"):
            return pos
        return ""

    def _my_entry(self, session):
        """Tu hueco en el champ select y la entrada que te corresponde.

        El cliente no siempre manda "cellId": puede ser "isLocalPlayer", el
        índice (myCellId) o el propio "cellId". Se prueban los tres.
        """
        my_team = session.get("myTeam") or []
        my_cell = session.get("myCellId")
        for e in my_team:
            if isinstance(e, dict) and e.get("isLocalPlayer"):
                return e, my_team.index(e)
        if isinstance(my_cell, int) and 0 <= my_cell < len(my_team):
            return my_team[my_cell], my_cell
        for i, e in enumerate(my_team):
            if isinstance(e, dict) and e.get("cellId") == my_cell:
                return e, i
        return None, -1

    def _hover_from_actions(self, session, my_cell, my_index):
        """El campeón que estás mirando ahora mismo (sin fijarlo todavía).

        En la fase de pick, la acción de tu celda lleva el championId del
        campeón sobre el que está el ratón.
        """
        actions = self._iter_actions(session)
        for act in reversed(actions):
            if str(act.get("type") or "pick").lower() == "ban":
                # En fase de baneo no interesa la build de a quien vas a banear.
                continue
            is_mine = act.get("isLocalPlayer")
            if not is_mine:
                cid = act.get("id")
                is_mine = (cid == my_cell) or (isinstance(my_index, int) and cid == my_index)
            if not is_mine:
                continue
            champ = int(act.get("championId") or 0)
            if champ:
                return champ, act
        return 0, None

    @staticmethod
    def _page_perks(page):
        """Los 9 perks de una página de runas, con nombre del propio cliente."""
        out = []
        for p in page.get("uiPerks") or []:
            pid = p.get("id")
            if not pid:
                continue
            out.append({
                "id": int(pid),
                "name": p.get("name") or "",
                "slot": p.get("slotType") or "",
                "style_id": p.get("styleId"),
                "icon": p.get("iconPath") or "",
            })
        if not out:
            for pid in page.get("selectedPerkIds") or []:
                out.append({"id": int(pid), "name": "", "slot": "", "style_id": None, "icon": ""})
        return out

    def _current_rune_page(self, lock):
        """La página de runas que estás EDITANDO ahora mismo en el cliente.

        Es lo que el champ select llama "currentpage": los 9 perks que has
        puesto, con el nombre tal cual lo escribe el cliente. Se usa para
        decirte qué falta cambiar respecto a lo que ya has configurado.
        """
        now = time.time()
        with self._lock:
            if now - self._page_cache["at"] < 2.0 and self._page_cache["data"] is not None:
                return self._page_cache["data"]
        data = self._get(lock, "/lol-perks/v1/currentpage")
        if not isinstance(data, dict) or not data.get("id"):
            # Respaldo: la página marcada como actual en la lista de páginas.
            pages = self._rune_pages(lock)
            data = None
            for p in pages or []:
                if p.get("current"):
                    data = p
                    break
            if data is None:
                with self._lock:
                    self._page_cache = {"at": now, "data": None}
                return None
        perks = self._page_perks(data)
        with self._lock:
            self._page_cache = {"at": now, "data": data}
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "is_temporary": bool(data.get("isTemporary")),
            "primary_style_id": data.get("primaryStyleId"),
            "primary_style_name": data.get("primaryStyleName"),
            "secondary_style_name": data.get("secondaryStyleName"),
            "perks": perks,
        }

    def _active_runes(self, lock):
        """Runas que tienes activas en el cliente (no inventadas: son las tuyas)."""
        pages = self._rune_pages(lock)
        if not pages:
            return None
        page = None
        for p in pages:
            if p.get("current"):
                page = p
                break
        if page is None:
            for p in pages:
                if p.get("isActive"):
                    page = p
                    break
        if page is None:
            return None
        perks = self._page_perks(page)
        if not perks:
            return None
        keystone = None
        for p in perks:
            if "KeyStone" in (p.get("slot") or ""):
                keystone = p
                break
        if keystone is None and page.get("pageKeystone"):
            pk = page["pageKeystone"]
            keystone = {"id": int(pk.get("id") or 0), "name": pk.get("name") or "",
                        "slot": "kKeyStone", "style_id": pk.get("styleId"), "icon": pk.get("iconPath") or ""}
        return {
            "page_id": page.get("id"),
            "page_name": page.get("name"),
            "primary_style_id": page.get("primaryStyleId"),
            "primary_style_name": page.get("primaryStyleName"),
            "secondary_style_name": page.get("secondaryStyleName"),
            "keystone": keystone,
            "perks": perks,
        }

    def _gameflow(self, lock):
        """Estado de la partida en el cliente (fase, jugadores, hechizos)."""
        now = time.time()
        with self._lock:
            if now - self._flow_cache["at"] < 2.0 and self._flow_cache["data"] is not None:
                return self._flow_cache["data"]
        data = self._get(lock, "/lol-gameflow/v1/session")
        if not isinstance(data, dict):
            return None
        with self._lock:
            self._flow_cache = {"at": now, "data": data}
        return data

    def _current_summoner(self, lock):
        summ = self._get(lock, "/lol-summoner/v1/current-summoner")
        if isinstance(summ, dict):
            return summ.get("puuid") or summ.get("summonerId")
        return None

    def _mode(self, lock):
        try:
            from .ddragon import mode_from_queue

            return mode_from_queue(self._queue_id(lock))
        except Exception:
            return None

    def poll(self, custom_path=None):
        result = {"available": False, "champion_id": None, "phase": None, "hovering": False, "enemies": [], "allies": [], "queue_id": None, "mode": None, "position": None, "locked": False, "hover_champion_id": None, "runes": None, "spells": None, "game_phase": None}
        lock_path = self._find_lockfile(custom_path)
        if not lock_path:
            with self._lock:
                self._cache = result
            return result
        try:
            lock = self._read_lockfile(lock_path)
            if not lock:
                with self._lock:
                    self._cache = result
                return result
            session = self._get(lock, "/lol-champ-select/v1/session")
            result["queue_id"] = self._queue_id(lock)
            result["mode"] = self._mode(lock)
            if session is None:
                # Fuera del champ select: seguimos con runas y partida.
                session = {}
            else:
                timer = session.get("timer") or {}
                result["available"] = True
                result["phase"] = timer.get("phase")
            my_cell = session.get("myCellId")
            my_team = session.get("myTeam") or []
            their_team = session.get("theirTeam") or []
            my_entry, my_index = self._my_entry(session)
            locked_cid = 0
            hover_cid = 0
            if my_entry:
                # (myTeam[].championId != 0) = campeón ya bloqueado.
                locked_cid = int(my_entry.get("championId") or 0)
                # Posición asignada (TOP/JUNGLE/MID/BOT/SUPPORT) para saber
                # qué build mirar aunque no coincida con tu config.
                pos = self._norm_position(my_entry.get("assignedPosition"))
                if pos:
                    result["position"] = pos
            # La champ-select actual lleva el campeón que estás viendo: sirve
            # como vista previa para tener la build ANTES de fijarlo.
            hover_cid, hover_act = self._hover_from_actions(session, my_cell, my_index)
            if hover_act:
                apos = self._norm_position(hover_act.get("assignedPosition"))
                if apos:
                    result["position"] = apos
            result["locked"] = locked_cid > 0
            result["hover_champion_id"] = hover_cid or None
            # Si ya está bloqueado, manda el bloqueado; si no, el que estás
            # viendo (vista previa para tener la build antes de fijar).
            result["champion_id"] = locked_cid or hover_cid or None
            result["allies"] = [
                int(e.get("championId") or 0)
                for i, e in enumerate(my_team)
                if isinstance(e, dict) and i != my_index
                and int(e.get("championId") or 0) > 0
            ]
            result["enemies"] = [
                int(e.get("championId") or 0)
                for e in their_team
                if isinstance(e, dict) and int(e.get("championId") or 0) > 0
            ]
            # Hechizos y runas que has elegido en ESTA partida (son las tuyas).
            if my_entry:
                spells = [int(my_entry.get("spell1Id") or 0), int(my_entry.get("spell2Id") or 0)]
                spells = [s for s in spells if s]
                if spells:
                    result["spells"] = spells
                perks = my_entry.get("perks") or my_entry.get("assignedPerks") or []
                flat = []
                if isinstance(perks, dict):
                    # Forma: {"perks": [...], "style": id, "styleName": ...}
                    for pid in perks.get("perks") or []:
                        try:
                            flat.append(int(pid))
                        except Exception:
                            pass
                    if perks.get("style"):
                        try:
                            flat.append(int(perks["style"]))
                        except Exception:
                            pass
                else:
                    for p in perks or []:
                        if isinstance(p, dict):
                            for pid in p.get("perks") or []:
                                try:
                                    flat.append(int(pid))
                                except Exception:
                                    pass
                            if p.get("style"):
                                try:
                                    flat.append(int(p["style"]))
                                except Exception:
                                    pass
                        else:
                            try:
                                flat.append(int(p))
                            except Exception:
                                pass
                if flat:
                    result["runes"] = {"ids": flat, "source": "champ select"}
        except Exception as e:
            # No se traga el error: se guarda para poder diagnosticarlo.
            result["error"] = repr(e)
        # Fuera del champ select: runas activas del cliente + fase de partida.
        if not result.get("runes"):
            try:
                runes = self._active_runes(lock)
                if runes:
                    runes["source"] = "página activa del cliente"
                    result["runes"] = runes
            except Exception:
                pass
        # La página de runas en edición: sirve para el diff del plan.
        try:
            page = self._current_rune_page(lock)
            if page:
                result["rune_page"] = page
        except Exception:
            pass
        try:
            flow = self._gameflow(lock)
            if isinstance(flow, dict):
                result["game_phase"] = flow.get("phase")
                if not result.get("spells"):
                    my_puuid = self._current_summoner(lock)
                    for sel in (flow.get("gameData") or {}).get("playerChampionSelections") or []:
                        if my_puuid and sel.get("puuid") == my_puuid:
                            sp = [int(sel.get("spell1Id") or 0), int(sel.get("spell2Id") or 0)]
                            result["spells"] = [s for s in sp if s] or None
                            break
        except Exception:
            pass
        with self._lock:
            self._cache = result
        return result

    def cached(self):
        with self._lock:
            return dict(self._cache)


lcu_client = LCUClient()
