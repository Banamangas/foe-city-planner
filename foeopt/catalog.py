from __future__ import annotations


def _ability_value(defn: dict, key: str) -> str | None:
    for ability in defn.get("abilities", []):
        if isinstance(ability, dict) and key in ability:
            return ability[key]
    return None


class Catalog:
    def __init__(self, defs: dict[str, dict]):
        self._defs = defs

    def _def(self, cityentity_id: str) -> dict:
        return self._defs.get(cityentity_id, {})

    def size(self, cityentity_id: str) -> tuple[int, int] | None:
        defn = self._def(cityentity_id)
        w, length = defn.get("width"), defn.get("length")
        if w and length:
            return (w, length)
        for comp in defn.get("components", {}).values():
            if not isinstance(comp, dict):
                continue
            placement = comp.get("placement")
            if isinstance(placement, dict):
                sz = placement.get("size")
                if isinstance(sz, dict) and sz.get("x") and sz.get("y"):
                    return (sz["x"], sz["y"])
        return None

    def street_requirement(self, cityentity_id: str) -> int:
        """The road level this entity requires, 0 if none. Older definitions
        declare it in `requirements.street_connection_level`, newer ones in a
        `components.<age>.streetConnectionRequirement` block."""
        defn = self._def(cityentity_id)
        lvl = (defn.get("requirements") or {}).get("street_connection_level")
        if lvl:
            return lvl
        for comp in (defn.get("components") or {}).values():
            req = comp.get("streetConnectionRequirement") if isinstance(comp, dict) else None
            if isinstance(req, dict):
                return req.get("requiredLevel") or 1
        return 0

    def required_level(self, cityentity_id: str) -> int:
        return self.street_requirement(cityentity_id) or 1

    # Streets carry their provided level in the same field.
    provided_level = required_level

    def set_id(self, cityentity_id: str) -> str | None:
        return _ability_value(self._def(cityentity_id), "setId")

    def _chain_block(self, cityentity_id: str) -> dict:
        """Newer definitions declare a chain in `components.<age>.chain`
        ({chainId, linkPositions}) instead of an ability."""
        for comp in (self._def(cityentity_id).get("components") or {}).values():
            block = comp.get("chain") if isinstance(comp, dict) else None
            if isinstance(block, dict):
                return block
        return {}

    def chain_id(self, cityentity_id: str) -> str | None:
        return (_ability_value(self._def(cityentity_id), "chainId")
                or self._chain_block(cityentity_id).get("chainId"))

    def link_positions(self, cityentity_id: str) -> tuple[tuple[int, int, int, int], ...]:
        """Chain linkPositions as inclusive (dx0, dy0, dx1, dy1) rectangles
        relative to the building's top-left; FoE omits zero coordinates."""
        rects = (_ability_value(self._def(cityentity_id), "linkPositions")
                 or self._chain_block(cityentity_id).get("linkPositions") or [])
        out = []
        for r in rects:
            tl, br = r.get("topLeftPoint") or {}, r.get("bottomRightPoint") or {}
            out.append((tl.get("x", 0), tl.get("y", 0), br.get("x", 0), br.get("y", 0)))
        return tuple(out)

    @property
    def known(self) -> bool:
        """True when catalog definitions were supplied (chains are detectable)."""
        return bool(self._defs)

    def name(self, cityentity_id: str) -> str:
        return self._def(cityentity_id).get("name", cityentity_id)
