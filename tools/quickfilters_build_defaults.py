DEFAULT_PRESETS = [
    ('All', '*'),
    ('Stone + ore', 'stone, @ore'),
    ('All farmed', 'wheat, berries, mushroom, flax, cotton, tealeaves, peppers, wood'),
    ('Base materials', 'wood, stone, @ore, rawfish, wheat, berries, mushroom, flax, cotton, tealeaves, peppers'),
    ('All food', '@rawFood, @foodTier1, @preparedFood, @mealFood'),
    ('Metal bars', 'copperbar, bronze, ironbar, steel, goldbar'),
]
DEFAULTS_TEXT = '|'.join(['[presets]'] + ['%s = %s' % kv for kv in DEFAULT_PRESETS])
