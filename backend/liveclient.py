import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LIVE_URL = "https://127.0.0.1:2999/liveclientdata/allgamedata"

ARAM_MAPS = {"howling abyss", "aram", "liquid map"}
TFT_MODES = {"tft", "turbo"}


class LiveClient:
    def __init__(self):
        self._session = requests.Session()
        self._session.verify = False

    def poll(self):
        try:
            r = self._session.get(LIVE_URL, timeout=0.6)
            if r.status_code != 200:
                return None
            return self._parse(r.json())
        except Exception:
            return None

    def _parse(self, data):
        active = data.get("activePlayer") or {}
        players = data.get("allPlayers") or []
        game_data = data.get("gameData") or {}
        scores = data.get("scores") or {}
        map_info = data.get("map") or {}

        my_name = active.get("summonerName")
        me = None
        for p in players:
            if p.get("summonerName") == my_name:
                me = p
                break
        if me is None and players:
            me = players[0]

        abilities = {}
        for key in ("Q", "W", "E", "R"):
            ab = (active.get("abilities") or {}).get(key) or {}
            abilities[key] = int(ab.get("abilityLevel", 0) or 0)

        items = []
        for it in active.get("items") or []:
            iid = it.get("itemID") or it.get("itemid")
            if iid:
                items.append(int(iid))

        my_team = str(me.get("team", "order")).lower() if me else "order"
        roster = []
        for p in players:
            pitems = []
            for it in p.get("items") or []:
                iid = it.get("itemID") or it.get("itemid")
                if iid:
                    pitems.append(int(iid))
            roster.append({
                "name": p.get("summonerName", ""),
                "champion": p.get("championName", ""),
                "team": str(p.get("team", "")).lower(),
                "level": p.get("level", 0),
                "mine": str(p.get("team", "")).lower() == my_team,
                "is_me": p is me,
                "scores": p.get("scores") or {},
                "items": pitems,
            })

        game_mode = str(game_data.get("gameMode", "")).upper()
        map_name = str(map_info.get("mapName", game_data.get("mapName", "")))
        try:
            queue_id = int(game_data.get("queueId") or 0)
        except Exception:
            queue_id = 0
        mode_hint = "normal"
        if "ARAM" in game_mode or "aram" in map_name.lower() or "howling" in map_name.lower():
            mode_hint = "aram"
        elif game_mode in ("CLASSIC", "TUTORIAL"):
            mode_hint = "normal"
        elif "TFT" in game_mode:
            mode_hint = "tft"
        try:
            from .ddragon import mode_from_queue

            mode_slug = mode_from_queue(queue_id) if queue_id else None
        except Exception:
            mode_slug = None

        kda = None
        sc = (me or {}).get("scores") or {}
        try:
            k = int(sc.get("kills", 0) or 0)
            d = int(sc.get("deaths", 0) or 0)
            a = int(sc.get("assists", 0) or 0)
            kda = {"kills": k, "deaths": d, "assists": a}
        except Exception:
            pass

        return {
            "champion": (active.get("championName") or (me or {}).get("championName") or ""),
            "gold": float(active.get("currentGold", 0) or 0),
            "level": int(active.get("level", 0) or 0),
            "items": items,
            "abilities": abilities,
            "game_time": float(data.get("gameTimer", game_data.get("gameLength", 0)) or 0),
            "mode_hint": mode_hint,
            "mode": mode_slug,
            "queue_id": queue_id,
            "map": map_name,
            "team": my_team,
            "players": roster,
            "kda": kda,
            "team_scores": {"red": scores.get("redScore", 0), "blue": scores.get("blueScore", 0)},
        }


live_client = LiveClient()


def mock_state():
    return {
        "champion": "Ahri",
        "gold": 1350.0,
        "level": 7,
        "items": [1056, 2003, 1001, 3144],
        "abilities": {"Q": 4, "W": 2, "E": 1, "R": 1},
        "game_time": 742.0,
        "mode_hint": "normal",
        "map": "Summoner's Rift",
        "team": "order",
        "players": [
            {"name": "Yo", "champion": "Ahri", "team": "order", "level": 7, "mine": True, "is_me": True, "scores": {}, "items": [1056, 2003, 1001, 3144]},
            {"name": "Ally1", "champion": "Garen", "team": "order", "level": 7, "mine": True, "is_me": False, "scores": {}, "items": [3047, 3078, 1011]},
            {"name": "Ally2", "champion": "Jinx", "team": "order", "level": 6, "mine": True, "is_me": False, "scores": {}, "items": [3006, 3004, 1038]},
            {"name": "Ally3", "champion": "Lulu", "team": "order", "level": 6, "mine": True, "is_me": False, "scores": {}, "items": [3853, 3158, 1004]},
            {"name": "Ally4", "champion": "Warwick", "team": "order", "level": 7, "mine": True, "is_me": False, "scores": {}, "items": [1401, 3111, 1001]},
            {"name": "Enemy1", "champion": "Yasuo", "team": "chaos", "level": 7, "mine": False, "is_me": False, "scores": {}, "items": [3006, 1038]},
            {"name": "Enemy2", "champion": "Lee Sin", "team": "chaos", "level": 6, "mine": False, "is_me": False, "scores": {}, "items": [1041, 1053]},
            {"name": "Enemy3", "champion": "Lux", "team": "chaos", "level": 7, "mine": False, "is_me": False, "scores": {}, "items": [1056, 3802]},
            {"name": "Enemy4", "champion": "Soraka", "team": "chaos", "level": 6, "mine": False, "is_me": False, "scores": {}, "items": [2003, 1004]},
            {"name": "Enemy5", "champion": "Aatrox", "team": "chaos", "level": 7, "mine": False, "is_me": False, "scores": {}, "items": [1055, 1053]},
        ],
        "kda": {"kills": 2, "deaths": 1, "assists": 4},
        "team_scores": {"red": 7, "blue": 5},
        "mock": True,
    }
