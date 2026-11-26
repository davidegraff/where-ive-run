"""Names of FIT sports and sub-sports, by the number stored in the file.

Copied from the FIT profile (as bundled with fitdecode 0.11). Numbers missing here are newer than
that profile; fit.py treats them as unknown, so the activity's type falls back to "Workout".
"""

SPORTS: dict[int, str] = {
    0: 'generic', 1: 'running', 2: 'cycling', 3: 'transition', 4: 'fitness_equipment', 5: 'swimming',
    6: 'basketball', 7: 'soccer', 8: 'tennis', 9: 'american_football', 10: 'training', 11: 'walking',
    12: 'cross_country_skiing', 13: 'alpine_skiing', 14: 'snowboarding', 15: 'rowing', 16: 'mountaineering',
    17: 'hiking', 18: 'multisport', 19: 'paddling', 20: 'flying', 21: 'e_biking', 22: 'motorcycling',
    23: 'boating', 24: 'driving', 25: 'golf', 26: 'hang_gliding', 27: 'horseback_riding', 28: 'hunting',
    29: 'fishing', 30: 'inline_skating', 31: 'rock_climbing', 32: 'sailing', 33: 'ice_skating',
    34: 'sky_diving', 35: 'snowshoeing', 36: 'snowmobiling', 37: 'stand_up_paddleboarding', 38: 'surfing',
    39: 'wakeboarding', 40: 'water_skiing', 41: 'kayaking', 42: 'rafting', 43: 'windsurfing',
    44: 'kitesurfing', 45: 'tactical', 46: 'jumpmaster', 47: 'boxing', 48: 'floor_climbing', 49: 'baseball',
    53: 'diving', 62: 'hiit', 64: 'racket', 65: 'wheelchair_push_walk', 66: 'wheelchair_push_run',
    67: 'meditation', 69: 'disc_golf', 71: 'cricket', 72: 'rugby', 73: 'hockey', 74: 'lacrosse',
    75: 'volleyball', 76: 'water_tubing', 77: 'wakesurfing', 80: 'mixed_martial_arts', 82: 'snorkeling',
    83: 'dance', 84: 'jump_rope', 254: 'all',
}

SUB_SPORTS: dict[int, str] = {
    0: 'generic', 1: 'treadmill', 2: 'street', 3: 'trail', 4: 'track', 5: 'spin', 6: 'indoor_cycling',
    7: 'road', 8: 'mountain', 9: 'downhill', 10: 'recumbent', 11: 'cyclocross', 12: 'hand_cycling',
    13: 'track_cycling', 14: 'indoor_rowing', 15: 'elliptical', 16: 'stair_climbing', 17: 'lap_swimming',
    18: 'open_water', 19: 'flexibility_training', 20: 'strength_training', 21: 'warm_up', 22: 'match',
    23: 'exercise', 24: 'challenge', 25: 'indoor_skiing', 26: 'cardio_training', 27: 'indoor_walking',
    28: 'e_bike_fitness', 29: 'bmx', 30: 'casual_walking', 31: 'speed_walking', 32: 'bike_to_run_transition',
    33: 'run_to_bike_transition', 34: 'swim_to_bike_transition', 35: 'atv', 36: 'motocross',
    37: 'backcountry', 38: 'resort', 39: 'rc_drone', 40: 'wingsuit', 41: 'whitewater', 42: 'skate_skiing',
    43: 'yoga', 44: 'pilates', 45: 'indoor_running', 46: 'gravel_cycling', 47: 'e_bike_mountain',
    48: 'commuting', 49: 'mixed_surface', 50: 'navigate', 51: 'track_me', 52: 'map', 53: 'single_gas_diving',
    54: 'multi_gas_diving', 55: 'gauge_diving', 56: 'apnea_diving', 57: 'apnea_hunting',
    58: 'virtual_activity', 59: 'obstacle', 62: 'breathing', 65: 'sail_race', 67: 'ultra',
    68: 'indoor_climbing', 69: 'bouldering', 70: 'hiit', 73: 'amrap', 74: 'emom', 75: 'tabata',
    84: 'pickleball', 85: 'padel', 86: 'indoor_wheelchair_walk', 87: 'indoor_wheelchair_run',
    88: 'indoor_hand_cycling', 94: 'squash', 95: 'badminton', 96: 'racquetball', 97: 'table_tennis',
    110: 'fly_canopy', 111: 'fly_paraglide', 112: 'fly_paramotor', 113: 'fly_pressurized',
    114: 'fly_navigate', 115: 'fly_timer', 116: 'fly_altimeter', 117: 'fly_wx', 118: 'fly_vfr',
    119: 'fly_ifr', 254: 'all',
}
