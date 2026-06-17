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

    def required_level(self, cityentity_id: str) -> int:
        lvl = self._def(cityentity_id).get("requirements", {}).get(
            "street_connection_level"
        )
        return lvl if lvl else 1

    # Streets carry their provided level in the same field.
    provided_level = required_level

    def set_id(self, cityentity_id: str) -> str | None:
        return _ability_value(self._def(cityentity_id), "setId")

    def chain_id(self, cityentity_id: str) -> str | None:
        return _ability_value(self._def(cityentity_id), "chainId")

    def name(self, cityentity_id: str) -> str:
        return self._def(cityentity_id).get("name", cityentity_id)
