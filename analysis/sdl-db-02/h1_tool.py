"""H1 tool and baselines of Spec sdl-db-02 (back-off conditional-frequency model; Python standard library only).

Reads one built DB (db/sdl-db.sqlite) through the views fixed by the Spec: v_era, v_step, v_connection,
db_record_coding, gold_membership, platform_identity_member. Nothing else is read.

Items
  (a) step:        every v_step row; target primary_module_type (rows with NULL target are counted and excluded).
                   Context: u = unit_operation, u_prev / u_next = unit operation of the previous / next step of the
                   same platform in step_order (START / END at the ends), t = first_field_tag.
  (b) connection:  v_connection rows with is_material = 1; target transfer_mode. A connection E (from module A to B)
                   is attached to the first consecutive step pair of its platform whose first modules are A then B;
                   otherwise to the last step with first module A before the first step with first module B, and that
                   B step; otherwise it is counted and excluded. u_from / u_to = the two steps' unit operations,
                   f_from / f_to = their families, t = first_field_tag.
Contexts, finest first (L5 = all items of the field):
  (a) L1 (u, u_prev, u_next, t)  L2 (u, u_prev, u_next)  L3 (u, t)  L4 (u)  L5
  (b) L1 (u_from, u_to, t)       L2 (u_from, u_to)       L3 (f_from, f_to, t)  L4 (f_from, f_to)  L5
Tool: use the finest level whose training count is >= m (L5 whatever m); predict its most frequent label; ties are
broken by the frequency at the next coarser level, then alphabetically. Top-3: the used level's ranking (same tie
rule), filled from coarser levels when it has fewer than three labels.
Baselines: (a) the most frequent module type of the unit operation (= L4); (b) the most frequent transfer mode of the
(f_from, f_to) pair (= L4); an unseen context falls back to the field's overall most frequent label (L5); ties
alphabetically; top-3 by frequency in the same context, filled from L5.
"""
from collections import Counter, defaultdict

START, END = "START", "END"
FIELDS = ("a", "b")


def load_items(db, era_only=None):
    """Return (items, excluded): items[field] = list of dicts; excluded = counts of items left out and why.
    era_only = 'train' reads only training-year rows (the SQL filters them; evaluation-year rows are never read)."""
    where = " WHERE era = ?" if era_only else ""
    arg = (era_only,) if era_only else ()
    era = {p: (y, e) for p, y, e in db.execute("SELECT paper_id, first_public_year, era FROM v_era" + where, arg)}
    steps = defaultdict(list)
    for r in db.execute("SELECT paper_id, coding_id, platform_id, step_id, step_order, unit_operation, family, performed_by, "
                        "primary_module_id, primary_module_type, first_field_tag, uncertain FROM v_step" + where, arg):
        steps[(r[0], r[2])].append(r)
    items = {"a": [], "b": []}
    excluded = Counter()
    first_mod = {}
    for (pid, plat), rows in steps.items():
        rows.sort(key=lambda r: r[4])
        first_mod[(pid, plat)] = rows
        for i, r in enumerate(rows):
            if r[9] is None:
                excluded["a_no_module"] += 1
                continue
            u_prev = rows[i - 1][5] if i > 0 else START
            u_next = rows[i + 1][5] if i + 1 < len(rows) else END
            items["a"].append({"paper": pid, "item": r[3], "platform": plat, "y": r[9], "t": r[10] or "",
                               "ctx": [(r[5], u_prev, u_next, r[10] or ""), (r[5], u_prev, u_next), (r[5], r[10] or ""), (r[5],)],
                               "unit": r[5], "uncertain": bool(r[11]), "performed_by": r[7],
                               "year": era[pid][0], "era": era[pid][1]})
    for r in db.execute("SELECT paper_id, platform_id, edge_id, from_module, to_module, transfer_mode, uncertain "
                        "FROM v_connection WHERE is_material = 1" + (" AND era = ?" if era_only else ""), arg):
        pid, plat, edge, a, b, mode, unc = r
        rows = first_mod.get((pid, plat), [])
        pair = None
        for i in range(len(rows) - 1):
            if rows[i][8] == a and rows[i + 1][8] == b:
                pair = (rows[i], rows[i + 1])
                break
        if pair is None:
            jb = next((j for j, s in enumerate(rows) if s[8] == b), None)
            if jb is not None:
                ia = [i for i in range(jb) if rows[i][8] == a]
                if ia:
                    pair = (rows[ia[-1]], rows[jb])
        if pair is None:
            excluded["b_unattached"] += 1
            continue
        sa, sb = pair
        t = sa[10] or ""
        items["b"].append({"paper": pid, "item": edge, "platform": plat, "y": mode, "t": t,
                           "ctx": [(sa[5], sb[5], t), (sa[5], sb[5]), (sa[6], sb[6], t), (sa[6], sb[6])],
                           "pair": (sa[6], sb[6]), "uncertain": bool(unc), "year": era[pid][0], "era": era[pid][1]})
    return items, excluded


def ranking(counter, fallback):
    """Labels ordered by count, ties by the fallback counters (coarser levels), then alphabetically."""
    return sorted(counter, key=lambda lab: tuple([-counter[lab]] + [-f.get(lab, 0) for f in fallback] + [lab]))


class Model:
    """Counts of labels per context level, fitted on a list of items of one field."""

    def __init__(self, items, m=None):
        self.m = m
        self.lev = [defaultdict(Counter) for _ in range(4)]
        self.all = Counter()
        for it in items:
            for k in range(4):
                self.lev[k][it["ctx"][k]][it["y"]] += 1
            self.all[it["y"]] += 1

    def _chain(self, it, start):
        """Counters from level `start` (0 = L1) down to L5."""
        return [self.lev[k].get(it["ctx"][k], Counter()) for k in range(start, 4)] + [self.all]

    def tool(self, it):
        """(top-1, top-3, level used 1..5)."""
        used = 4
        for k in range(4):
            if sum(self.lev[k].get(it["ctx"][k], Counter()).values()) >= self.m:
                used = k
                break
        chain = self._chain(it, used)
        top = []
        for j, c in enumerate(chain):
            for lab in ranking(c, chain[j + 1:j + 2]):
                if lab not in top:
                    top.append(lab)
            if len(top) >= 3:
                break
        return top[0], top[:3], used + 1

    def baseline(self, it):
        """(top-1, top-3): the L4 context (unit operation / family pair), unseen -> L5; ties alphabetical."""
        c = self.lev[3].get(it["ctx"][3], Counter())
        top = sorted(c, key=lambda lab: (-c[lab], lab))
        for lab in sorted(self.all, key=lambda lab: (-self.all[lab], lab)):
            if lab not in top:
                top.append(lab)
        return top[0], top[:3]
