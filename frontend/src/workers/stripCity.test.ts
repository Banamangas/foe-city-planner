import { describe, it, expect } from "vitest";
import { stripCity } from "./stripCity";

const fat = {
  CityMapData: { a: { id: 1, x: 0, y: 0, cityentity_id: "E1" } },
  UnlockedAreas: [{ x: 0, y: 0, width: 4, length: 4 }],
  CityEntities: {
    E1: {
      id: "E1", width: 5, length: 5, name: "Armory", type: "military",
      asset_id: "junk", stateDefinitionHash: "junk", entity_levels: [1, 2, 3],
      requirements: { street_connection_level: 2, other: "drop" },
      abilities: [
        { __class__: "SetAbility", setId: "S1", reward: "drop" },
        { __class__: "ChainAbility", chainId: "C1" },
        { __class__: "BoostAbility", value: 999 },
      ],
      components: {
        p: { placement: { size: { x: 5, y: 5 } }, asset: "drop", state: "drop" },
      },
    },
    E2: { id: "E2", name: "NoSize", components: { c: { placement: { size: { x: 2, y: 3 } } } } },
  },
};

describe("stripCity", () => {
  it("passes CityMapData and UnlockedAreas through unchanged", () => {
    const slim = stripCity(fat);
    expect(slim.CityMapData).toEqual(fat.CityMapData);
    expect(slim.UnlockedAreas).toEqual(fat.UnlockedAreas);
  });

  it("keeps only catalog fields on entities", () => {
    const e = stripCity(fat).CityEntities.E1;
    expect(e).toEqual({
      id: "E1", width: 5, length: 5, name: "Armory",
      requirements: { street_connection_level: 2 },
      abilities: [{ setId: "S1" }, { chainId: "C1" }, {}],
      components: { p: { placement: { size: { x: 5, y: 5 } } } },
    });
  });

  it("omits missing fields instead of inventing them", () => {
    const e = stripCity(fat).CityEntities.E2;
    expect(e.width).toBeUndefined();
    expect(e.requirements).toBeUndefined();
    expect(e.components).toEqual({ c: { placement: { size: { x: 2, y: 3 } } } });
  });
});
