type AnyObj = Record<string, any>;

function slimAbility(ability: AnyObj): AnyObj {
  const out: AnyObj = {};
  if ("setId" in ability) out.setId = ability.setId;
  if ("chainId" in ability) out.chainId = ability.chainId;
  return out;
}

function slimComponents(components: AnyObj): AnyObj {
  const out: AnyObj = {};
  for (const key of Object.keys(components)) {
    const size = components[key]?.placement?.size;
    if (size !== undefined) out[key] = { placement: { size } };
  }
  return out;
}

function slimEntity(entity: AnyObj): AnyObj {
  const out: AnyObj = {};
  if ("id" in entity) out.id = entity.id;
  if ("width" in entity) out.width = entity.width;
  if ("length" in entity) out.length = entity.length;
  if ("name" in entity) out.name = entity.name;
  const scl = entity?.requirements?.street_connection_level;
  if (scl !== undefined) out.requirements = { street_connection_level: scl };
  if (Array.isArray(entity.abilities)) out.abilities = entity.abilities.map(slimAbility);
  if (entity.components && typeof entity.components === "object") {
    const c = slimComponents(entity.components);
    if (Object.keys(c).length > 0) out.components = c;
  }
  return out;
}

export function stripCity(data: AnyObj): AnyObj {
  const entities: AnyObj = {};
  const src = data.CityEntities ?? {};
  for (const id of Object.keys(src)) {
    entities[id] = slimEntity(src[id]);
  }
  return {
    CityMapData: data.CityMapData ?? {},
    UnlockedAreas: data.UnlockedAreas ?? [],
    CityEntities: entities,
  };
}
