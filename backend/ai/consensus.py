"""Fusión de varias respuestas ya validadas (mismo esquema que aiadvisor.parse_reply).

Cada respuesta llega validada contra el catálogo cerrado, así que la fusión solo puede combinar ids
reales; nunca introduce objetos nuevos. Se conserva quién aportó cada decisión (`by`).
"""
import json


def merge(replies):
    """replies: [(proveedor, parsed)] en orden de prioridad. Devuelve (dict en el esquema de parse_reply, by)."""
    n = len(replies)
    pts, pos, why, voters = {}, {}, {}, {}
    for prov, p in replies:
        build = p.get("build") or []
        for i, it in enumerate(build):
            iid = it["id"]
            pts[iid] = pts.get(iid, 0) + (6 - i)                 # Borda: el 1.º vale 6, el 6.º vale 1
            pos.setdefault(iid, []).append(i)
            voters.setdefault(iid, []).append(prov)
            if it.get("why") and (iid not in why or i < why[iid][0]):
                why[iid] = (i, it["why"])
    order = sorted(pts, key=lambda k: (-pts[k], sum(pos[k]) / len(pos[k]), k))
    build = [{"id": k, "why": why.get(k, (0, ""))[1]} for k in order[:6]]

    scores, pwhy = {}, {}
    for prov, p in replies:
        for it in p.get("picks") or []:
            scores.setdefault(it["id"], []).append(it["score"])
            if it.get("why") and (it["id"] not in pwhy or it["score"] > pwhy[it["id"]][0]):
                pwhy[it["id"]] = (it["score"], it["why"])
    mean = {k: sum(v) / len(v) for k, v in scores.items()}
    picks = [{"id": k, "score": round(mean[k], 1), "why": pwhy.get(k, (0, ""))[1]}
             for k in sorted(mean, key=lambda k: (-mean[k], k))[:6]]

    votes = {}
    avoid_why = {}
    for prov, p in replies:
        for it in p.get("avoid") or []:
            votes[it["id"]] = votes.get(it["id"], 0) + 1
            avoid_why.setdefault(it["id"], it.get("why", ""))
    strong = {p["id"] for p in picks if p["score"] >= 60}
    avoid = [{"id": k, "why": avoid_why[k]} for k in sorted(votes, key=lambda k: -votes[k])
             if votes[k] * 2 > n and k not in strong][:3]          # mayoría estricta

    resumen = next((p.get("resumen") for _, p in replies if p.get("resumen")), "")
    alert = next((p.get("alert") for _, p in replies if p.get("alert")), "")
    merged = {"picks": picks, "avoid": avoid, "build": build, "resumen": resumen, "alert": alert}
    by = {"build": {k: voters[k] for k in order[:6]}, "providers": [prov for prov, _ in replies],
          "unanimous_build": [k for k in order[:6] if len(voters[k]) == n]}
    return merged, by


def to_text(merged):
    """Texto JSON que vuelve a pasar por parse_reply (misma validación que una respuesta normal)."""
    return json.dumps(merged, ensure_ascii=False)
