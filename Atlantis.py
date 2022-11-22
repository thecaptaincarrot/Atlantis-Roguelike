#fix take damage
import tcod as libtcod
import math
import textwrap
import shelve
import copy
import time

SCREEN_WIDTH = 80
SCREEN_HEIGHT = 60
LIMIT_FPS = 20

CAMERA_WIDTH = 80
CAMERA_HEIGHT = 43

MAP_WIDTH = 80
MAP_HEIGHT = 80

color_dark_wall = libtcod.darkest_grey
color_light_wall = libtcod.grey
color_dark_ground = libtcod.darker_sepia
color_light_ground = libtcod.sepia

ROOM_MAX_SIZE = 10
ROOM_MIN_SIZE = 6
MAX_ROOMS = 30

MAX_ROOM_MONSTERS = 3
MAX_ROOM_ITEMS = 2

FOV_ALGO = 0
FOV_LIGHT_WALLS = True
TORCH_RADIUS = 10

BAR_WIDTH = 20
PANEL_HEIGHT = 7
PANEL_Y = SCREEN_HEIGHT - PANEL_HEIGHT

MSG_X = 30
MSG_WIDTH = SCREEN_WIDTH - MSG_X - 2
MSG_HEIGHT = PANEL_HEIGHT - 1

INVENTORY_WIDTH = 50



class Tile:
	#map tile
	def __init__(self, blocked, block_sight = None):
		self.blocked = blocked
		#default to blocked sight if blocked and not specified
		self.explored = False
		if block_sight is None: block_sight = blocked
		self.block_sight = block_sight

class rect:
	def __init__(self, x, y, w, h):
		self.x1 = x
		self.y1 = y
		self.x2 = x + w
		self.y2 = y + h
		
	def center(self):
		center_x = (self.x1 + self.x2) // 2
		center_y = (self.y1 + self.y2) // 2
		return (center_x, center_y)
	
	def intersect(self, other):
		#returns true if this rectangle intersects with others
		return (self.x1 <= other.x2 and self.x2 >= other.x1 and
			self.y1 <= other.y2 and self.y2 >= other.y1)

def square_from_center(centerx,centery,r):
	x = int(math.floor(centerx - r))
	y = int(math.floor(centery - r))
	w = int(math.floor(r * 2))
	h = int(math.floor(r * 2))
	return rect(x,y,w,h)
			
class tunnel:
	def __init__(self, x, y, theta, length):
		self.x = x
		self.y = y
		self.theta = theta
		self.length = length
		self.endx = x + math.floor(length * math.cos(theta))
		self.endy = y + math.floor(length * math.sin(theta))
	def dig_tunnel(self):
		global map
		for r in range(0, self.length):
			x1 = math.floor(self.x) + math.floor(r*math.cos(self.theta))
			y1 = math.floor(self.y) + math.floor(r*math.sin(self.theta))
			for x in range(x1 - 1, x1 + 1):
				for y in range (y1 - 1, y1 + 1):
						try:
							map[x][y].blocked = False
							map[x][y].block_sight = False
							map[x][y].explored = True
						except:
							return 'failed'
			
class Object:
	#this is a generic object: the player, a monster, an item, the stairs...
	#it's always represented by a character on screen.
	def __init__(self, x, y, char, name, color, description = ' ', blocks=False, creature=None, ai=None, item = None, ghost=False, always_visible = None, equipment = None, weapon = None):
		self.x = x
		self.y = y
		self.char = char
		self.name = name
		self.color = color
		self.blocks = blocks
		self.creature = creature
		self.ghost = ghost
		self.item = item
		self.always_visible = always_visible
		self.equipment = equipment
		self.description = description
		self.weapon = weapon
		
		if self.weapon:
			self.weapon.owner = self
			self.equipment = Equipment(slot = "Right Hand", power_bonus = self.weapon.power_bonus, defense_bonus = self.weapon.power_bonus)
			self.item = Item()
		
		if self.equipment:
			self.equipment.owner = self
			self.item = Item()
			
		if self.item:
			self.item.owner = self
		
		if self.creature:  #let the creature component know who owns it
			self.creature.owner = self
 
		self.ai = ai
		if self.ai:  #let the AI component know who owns it
			self.ai.owner = self
 
	def move(self, dx, dy):
		#move by the given amount, if the destination is not blocked
		try:
			if not is_blocked(self.x + dx, self.y - dy) or self.ghost:
				self.x += dx
				self.y -= dy
		except IndexError:
			pass
 
	def move_towards(self, target_x, target_y):
		#vector from this object to the target, and distance
		dx = target_x - self.x
		dy = target_y - self.y
		distance = math.sqrt(dx ** 2 + dy ** 2)
 
		#normalize  it to length 1 (preserving direction), then round it and
		#convert to integer so the movement is restricted to the map grid
		dx = int(round(dx / distance))
		dy = int(round(dy / distance))
		self.move(dx, -dy)
 
	def distance_to(self, other):
		#return the distance to another object
		dx = other.x - self.x
		dy = other.y - self.y
		return math.sqrt(dx ** 2 + dy ** 2)
	def distance (self, x, y):
		return math.sqrt((x-self.x) ** 2 + (y-self.y) ** 2 )
 
	def draw(self):
		#only show if it's visible to the player
		if libtcod.map_is_in_fov(fov_map, self.x, self.y):
			(x, y) = to_camera_coordinates(self.x, self.y)
 
			if x is not None:
				#set the color and then draw the character that represents this object at its position
				libtcod.console_set_default_foreground(con, self.color)
				libtcod.console_put_char(con, x, y, self.char, libtcod.BKGND_NONE)
 
	def clear(self):
		#erase the character that represents this object
		(x, y) = to_camera_coordinates(self.x, self.y)
		if x is not None:
			libtcod.console_put_char(con, x, y, ' ', libtcod.BKGND_NONE)
		
	def send_to_back(self):
		global objects
		objects.remove(self)
		objects.insert(0,self)
	
	
	
	def move_astar(self, target):
		#Create a FOV map that has the dimensions of the map
		fov = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
 
		#Scan the current map each turn and set all the walls as unwalkable
		for y1 in range(MAP_HEIGHT):
			for x1 in range(MAP_WIDTH):
				libtcod.map_set_properties(fov, x1, y1, not map[x1][y1].block_sight, not map[x1][y1].blocked)
 
		#Scan all the objects to see if there are objects that must be navigated around
		#Check also that the object isn't self or the target (so that the start and the end points are free)
		#The AI class handles the situation if self is next to the target so it will not use this A* function anyway   
		for obj in objects:
			if obj.blocks and obj != self and obj != target:
				#Set the tile as a wall so it must be navigated around
				libtcod.map_set_properties(fov, obj.x, obj.y, True, False)
 
		#Allocate a A* path
		#The 1.41 is the normal diagonal cost of moving, it can be set as 0.0 if diagonal moves are prohibited
		my_path = libtcod.path_new_using_map(fov, 1.41)
 
		#Compute the path between self's coordinates and the target's coordinates
		libtcod.path_compute(my_path, self.x, self.y, target.x, target.y)
 
		#Check if the path exists, and in this case, also the path is shorter than 25 tiles
		#The path size matters if you want the monster to use alternative longer paths (for example through other rooms) if for example the player is in a corridor
		#It makes sense to keep path size relatively low to keep the monsters from running around the map if there's an alternative path really far away		
		if not libtcod.path_is_empty(my_path) and libtcod.path_size(my_path) < 25:
			#Find the next coordinates in the computed full path
			x, y = libtcod.path_walk(my_path, True)
			if x or y:
				#Set self's coordinates to the next path tile
				self.x = x
				self.y = y
		else:
			#Keep the old move function as a backup so that if there are no paths (for example another monster blocks a corridor)
			#it will still try to move towards the player (closer to the corridor opening)
			self.move_towards(target.x, target.y)  
 
		#Delete the path to free memory
		libtcod.path_delete(my_path)

class fluid:
	def __init__(self, depth = 1, density = 1, step_function = None):
		self.depth = depth
		self.density = density

class creature:
	def __init__(self, blood, trauma,  defense, power, speed, xp, wounds = 0, heal_rate = 300, blood_fluid = None, death_function=None, drop_dict = {'Nothing':-1}):
		self.death_function = death_function
		self.max_blood = blood
		self.blood = blood
		self.wounds = wounds
		self.max_trauma = trauma
		self.trauma = trauma
		self.heal_rate = heal_rate
		self.base_defense = defense
		self.base_speed = speed
		self.base_power = power
		self.xp = xp
		self.bleed_clock = 100
		self.heal_clock = heal_rate
		self.blood_fluid = blood_fluid
		self.drop_dict = drop_dict
		
	@property
	def power(self):
		bonus = sum(equipment.power_bonus for equipment in get_all_equipped(self.owner))
		return self.base_power+bonus
	
	@property
	def defense(self):
		bonus =  sum(equipment.defense_bonus for equipment in get_all_equipped(self.owner))
		return self.base_defense+bonus
	
	@property
	def speed(self):
		bonus = sum(equipment.speed_bonus for equipment in get_all_equipped(self.owner))
		return self.base_speed + bonus
	
	def take_damage(self, damage, ratio):
		if self.blood > 0 or self.blood is None:
			damage = math.ceil(damage - (self.defense / 2))
			if damage < 0:
				damage = 0
			wounds = math.ceil(damage * ratio) - self.defense/2# - math.floor(self.defense/10))
			if wounds <=0:
				wounds = 0
			trauma = math.ceil(damage - wounds) + self.defense / 2
			if trauma >= damage:
				trauma = damage
			if self.trauma <= 5:
				wounds += trauma
			self.trauma -= trauma
			if self.trauma <=0:
				self.trauma = 0
			self.wounds += wounds
			
	def bleed(self, time):
		monster = self.owner
		self.bleed_clock -= time
		self.heal_clock -= time
		while self.bleed_clock <= 0:
			self.blood -= self.wounds
			self.bleed_clock += 100
			heavy_bleeding = self.wounds
			# if self.blood_fluid is not None:
				# while heavy_bleeding >= 5:
					# print "heavy bleeding: " + str(heavy_bleeding)
					# heavy_bleeding -= 5
					# blood = copy.deepcopy(self.blood_fluid)
					# blood.x = self.owner.x
					# blood.y = self.owner.y
					# objects.insert(0,blood)
		
		while self.heal_clock <= 0:
			self.wounds -= math.ceil(self.wounds/5)
			if self.wounds <0:
				self.wounds = 0
			self.trauma += 1
			if self.trauma > self.max_trauma:
				self.trauma = self.max_trauma
			self.heal_clock += self.heal_rate
		if self.blood <= 0:
			self.death_function(self.owner, self.drop_dict)
		

			
	def attack (self, target):
		ratio = .25
		speed_mod = 1.5
		damage_mod = 1.3
		flavor_text = "you give 'em a little smack"
		message(flavor_text)
		damage = self.power * damage_mod
		target.creature.take_damage(damage, ratio)
		
	def heal(self, amount):
		#heal by the given amount, without going over the maximum
		self.hp += amount
		if self.hp > self.max_hp:
			self.hp = self.max_hp

class BasicMonster:
	def __init__(self, speed, attack_function = None, attack_probs = None):
		self.speed = speed
		self.clock  = speed
		self.attack_function = attack_function
		self.attack_probs = attack_probs#this should be a list with probabilities
	
	def take_turn(self, time):
		monster = self.owner
		monster.creature.bleed(time)
		if monster.creature is not None:
			if libtcod.map_is_in_fov(fov_map, monster.x, monster.y):
				self.clock -= time
			while self.clock < 0:
				clock = 0
				if monster.distance_to(player) >= 2:
					monster.move_astar(player)
					self.clock += self.owner.creature.speed
				elif player.creature.blood > 0:
					attack_len=len(self.attack_function)
					probsum = sum(self.attack_probs)
					dice = libtcod.random_get_int(0,0,probsum)
					bigsum = 0
					count = 0
					for probability in self.attack_probs:
						bigsum += probability
						if dice < bigsum:
							self.clock += self.attack_function[count](monster, player)
							break
						count += 1

						
class Item:
	#an item that can be picked up and used.
	def __init__(self, use_function = None):
		self.use_function = use_function
				
	def use(self):
		
		if self.owner.equipment:
			self.owner.equipment.toggle_equip()
			return 400
		
		if self.use_function is None:
			message('The ' + self.owner.name + ' cannot be used.')
		else:
			if self.use_function() != 'cancelled':
				inventory.remove(self.owner)
					
	def pick_up(self):
		#add to the player's inventory and remove from the map
		if len(inventory) >= 26:
			message('Your inventory is full, cannot pick up ' + self.owner.name + '.', libtcod.red)
		else:
			inventory.append(self.owner)
			objects.remove(self.owner)
			message('You picked up a ' + self.owner.name + '!', libtcod.green)
	def drop(self):
		objects.append(self.owner)
		inventory.remove(self.owner)
		self.owner.x=player.x
		self.owner.y = player.y
		if self.owner.equipment:
			self.owner.equipment.dequip()
		message('You dropped a ' + self.owner.name, libtcod.gray)

class Equipment:
	
	def __init__(self, slot, power_bonus = 0, defense_bonus = 0, max_hp_bonus = 0, speed_bonus = 0, weapon = None):
		self.slot = slot
		self.is_equipped = False
		self.power_bonus = power_bonus
		self.defense_bonus = defense_bonus
		self.max_hp_bonus = max_hp_bonus
		self.speed_bonus = speed_bonus
		
	def toggle_equip(self):
		if self.is_equipped:
			self.dequip()
		else:
			self.equip()
	
	def equip(self):
		
		old_equipment = get_equipped_in_slot(self.slot)
		if old_equipment is not None:
			old_equipment.dequip()
		self.is_equipped = True
		message('Equipped ' + self.owner.name + ' on ' + self.slot + '.', libtcod.light_green)
	
	def dequip(self):
		if not self.is_equipped: return
		self.is_equipped = False
		message('Dequipped ' + self.owner.name + ' from ' + self.slot + '.', libtcod.light_yellow)
		
def get_all_equipped(obj):
	if obj == player:
		equipped_list = []
		for item in inventory:
			if item.equipment and item.equipment.is_equipped:
				equipped_list.append(item.equipment)
		return equipped_list
	else:
		return []

def get_weapon(obj):
	
	if obj == player:
		equipped_list = []
		for item in inventory:
			if item.weapon and item.equipment.is_equipped:
				return item.weapon
	else:
		return None
		
class Weapon:
	
	def __init__(self, slot, power_bonus = 0, defense_bonus = 0, ratio = 1, speed_mod = 1, damage_mod = 1):
		self.slot = slot
		self.power_bonus = power_bonus
		self.defense_bonus = defense_bonus
		self.ratio = ratio
		self.speed_mod = speed_mod
		self.damage_mod = damage_mod
#################################################
##################MONSTER ATTACKS################
#################################################
#check if hit
#execute take damage on target
#return attack speed

def check_hit(fighter, target):
	wound_mod = (2 * fighter.trauma + fighter.blood)/(2 * fighter.max_trauma + fighter.max_blood)
	hit_check = math.ceil(wound_mod*((1.0 *fighter.speed)/target.speed)*100)
	dice = libtcod.random_get_int(0,0,100)
	if dice <=  hit_check:
		return True
	else:
		return False

#player weapon attack
def weapon_attack(fighter, target):
	ratio = .35
	speed_mod = 1
	damage_mod = .5
	hit_text = "You take a mighty swing with your fists, striking your opponent"
	miss_text = "You miss with your fists like the scrub you are"
	weapon = get_weapon(fighter)
	if weapon is not None:
		ratio = weapon.ratio
		speed_mod = weapon.speed_mod
		damage_mod = weapon.ratio
		hit_text = "You take a mighty swing with your " + weapon.owner.name + ", striking your opponent"
		miss_text = "You miss with your " + weapon.owner.name + " like the scrub you are"
	hitcheck = check_hit(fighter.creature, target.creature)
	if hitcheck:
		message(hit_text)
		damage = fighter.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
		
#general bitery
def bite(monster, target):
	ratio = .5
	speed_mod = 1
	damage_mod = 1
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' lunges forwards, sinking its teeth into you and drawing blood.'
	miss_text = 'The ' + monster.name.capitalize() + ' lunges forwards, but you dodge clear!'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod

def fist(monster, target):
	ratio = .2
	speed_mod = 1
	damage_mod = 1
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' slaps you across the face.'
	miss_text = 'The ' + monster.name.capitalize() + ' lunges forwards, but you dodge clear!'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod
	
#creatures with horns
def ram(monster, target):
	ratio = .25
	speed_mod = 1.5
	damage_mod = 1.3
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' rears back and rams you with its horns, staggering you.'
	miss_text = 'The ' + monster.name.capitalize() + ' rears back but misses you with its horns.'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod
	
#Errybody with a club getting hitsy
def club(monster, target):
	ratio = .2
	speed_mod = 1.1
	damage_mod = .75
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' attacks you with a simple club. It hurts a lot!'
	miss_text = 'The ' + monster.name.capitalize() + ' swings its club but you nimbly dodge aside.'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod

def hammer(monster, target):
	ratio = .2
	speed_mod = 1.2
	damage_mod = 1.1
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' attacks you with a hammer. It hurts a lot!'
	miss_text = 'The ' + monster.name.capitalize() + ' swings its club but you nimbly dodge aside.'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod
	
def blade(monster, target):
	ratio = .65
	speed_mod = 1
	damage_mod = 1.1
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' attacks you with a blade. It hurts a lot!'
	miss_text = 'The ' + monster.name.capitalize() + ' swings its blade but you nimbly dodge aside.'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod

def spear(monster, target):
	ratio = .8
	speed_mod = 1
	damage_mod = 1
	hitcheck = check_hit(monster.creature, target.creature)
	hit_text = 'The ' + monster.name.capitalize() + ' attacks you with a spear. It hurts a lot!'
	miss_text = 'The ' + monster.name.capitalize() + ' swipes its spear but you nimbly dodge aside.'
	if hitcheck:
		message(hit_text)
		damage = monster.creature.power * damage_mod
		target.creature.take_damage(damage, ratio)
	else:
		message(miss_text)
	return monster.creature.speed*speed_mod
	
##################################################
##################ITEM FUNCTIONS##################
##################################################
def cast_heal():
	if player.creature.hp == player.creature.max_hp:
		message('You are already at full health.', libtcod.yellow)
		return "cancelled"
	message('Your wounds start to close.', libtcod.light_violet)
	player.creature.heal(4)

def cast_lightning():
	monster = closest_monster(5)
	if monster is None:
		message ("No enemy is in range.", libtcod.light_red)
		return 'cancelled'
		
	message('A lightning bolt strikes the ' + monster.name + ' for 20 damage.', libtcod.light_blue)
	monster.creature.take_damage(20)

def cast_fireball():
	
	target = get_target_monster(6)
	if target is None: return 'cancelled'
	
	message('A ball of fire bursts from your hand, burning the ' + target.name + ' for 10 damage')
	
	target.creature.take_damage(10)

def bandage():
	player.creature.wounds -=5
	if player.creature.wounds<0:
		player.creature.wounds = 0
	message('you take a moment to bind your wounds', libtcod.light_red)
	
def get_target(max_range = None):
	global game_state
	global playerx, playery, fov_recompute, game_state
	global lk_cursor, objects
	game_state = 'aiming'

	# create look cursor
	lk_cursor = Object(player.x, player.y, 'X', 'Cursor', libtcod.red, ghost = True, always_visible = True)
	objects.insert(0,lk_cursor)
	while not libtcod.console_is_window_closed():
		(x,y) = (lk_cursor.x, lk_cursor.y)
		libtcod.console_set_default_foreground(con, libtcod.white)
		
		render_all()

		libtcod.console_flush()

		for object in objects:
			object.clear()

		key = libtcod.console_wait_for_keypress(True)
		if key.vk == libtcod.KEY_KP8:
			lk_cursor.move(0,1)
		elif key.vk == libtcod.KEY_KP2:
			lk_cursor.move(0, -1)
		elif key.vk == libtcod.KEY_KP6:
			lk_cursor.move(1, 0)
		elif key.vk == libtcod.KEY_KP4:
			lk_cursor.move(-1, 0)
		elif key.vk == libtcod.KEY_KP7:
			lk_cursor.move(-1, 1)
		elif key.vk == libtcod.KEY_KP9:
			lk_cursor.move(1, 1)
		elif key.vk == libtcod.KEY_KP1:
			lk_cursor.move(-1, -1)
		elif key.vk == libtcod.KEY_KP3:
			lk_cursor.move(1, -1)
		elif key.vk == libtcod.KEY_KP4:
			lk_cursor.move(-1, 0)
		elif key.vk == libtcod.KEY_KPENTER or key.vk == libtcod.KEY_ENTER:
			objects.remove(lk_cursor)
			game_state = 'playing'
			return (x,y)
			
	
	
def get_target_monster(max_range = None):
	(x,y) = get_target(max_range)
	if x is None:
		return None
	for obj in objects:
		if obj.x == x and obj.y == y and obj.creature and obj!= player:
			return obj
	
def closest_monster(max_range):
	closest_enemy = None
	closest_dist = max_range + 1
	
	for object in objects:
		if object.creature and not object == player and libtcod.map_is_in_fov(fov_map, object.x, object.y):
			dist = player.distance_to(object)
			if dist < closest_dist:
				closest_enemy = object
				closest_dist = dist
	return closest_enemy

def get_equipped_in_slot(slot):
	for obj in inventory:
		if obj.equipment and obj.equipment.slot == slot and obj.equipment.is_equipped:
			return obj.equipment
	return None
	
def menu(header, options, width):
	if len(options) > 26: raise ValueError('Cannot have more than 26 options')
	
	header_height = libtcod.console_get_height_rect(con, 0,0, width, SCREEN_HEIGHT, header)
	height = len(options) + header_height
	
	window = libtcod.console_new(width, height)
	libtcod.console_set_default_foreground(window, libtcod.white)
	libtcod.console_print_rect_ex(window, 0, 0, width, height, libtcod.BKGND_NONE, libtcod.LEFT, header)
	
	y = header_height
	letter_index = ord('a')
	for option_text in options:
		text  = '(' + chr(letter_index) + ') ' + option_text
		libtcod.console_print_ex(window, 0,y, libtcod.BKGND_NONE, libtcod.LEFT, text)
		y += 1
		letter_index += 1
	x = SCREEN_WIDTH/2 - width / 2
	y = SCREEN_HEIGHT / 2 - height/2
	libtcod.console_blit(window, 0, 0, width, height, 0, x, y, 1.0, 0.7)
	
	libtcod.console_flush()
	key = libtcod.console_wait_for_keypress(True)
	
	index = key.c - ord('a')
	if index >= 0 and index < len(options): return index
	return None

def inventory_menu(header):
	#show a menu with each item of the inventory as an option
	if len(inventory) == 0:
		options = ['Inventory is empty.']
	else:
		options = []
		for item in inventory:
			text = item.name
			
			if item.equipment and item.equipment.is_equipped:
				text = text + ' (on ' + item.equipment.slot + ')'
			options.append(text)
 
	index = menu(header, options, INVENTORY_WIDTH)
 
	#if an item was chosen, return it
	if index is None or len(inventory) == 0: return None
	return inventory[index].item

	
def player_death(player, drop_dict):
	global game_state
	message( 'you died!', libtcod.purple)
	game_state = 'dead'
	
	player.char = '%'
	player.color = libtcod.dark_red

def monster_death(monster, drop_dict):
	message( monster.name.capitalize() + ' is dead', libtcod.yellow)
	monster.char = '%'
	monster.color = libtcod.dark_red
	player.creature.xp += monster.creature.xp
	monster.blocks = False
	monster.creature = None
	monster.ai = None
	monster.name = 'remains of ' + monster.name
	monster.send_to_back()
	item_drop(monster.x,monster.y,drop_dict)
	
	
def item_drop(x,y, drop_dict):
	dice = 100
	for key, value in drop_dict.iteritems():
		dice = libtcod.random_get_int(0,0,100)
		if dice <= value:
			object = item_define(key,x,y)
			objects.append(object)

		

def move_camera(target_x, target_y):
	global camera_x, camera_y, fov_recompute
 
	#new camera coordinates (top-left corner of the screen relative to the map)
	x = target_x - CAMERA_WIDTH / 2  #coordinates so that the target is at the center of the screen
	y = target_y - CAMERA_HEIGHT / 2
 
	#make sure the camera doesn't see outside the map
	if x < 0: x = 0
	if y < 0: y = 0
	if x > MAP_WIDTH - CAMERA_WIDTH - 1: x = MAP_WIDTH - CAMERA_WIDTH - 1
	if y > MAP_HEIGHT - CAMERA_HEIGHT - 1: y = MAP_HEIGHT - CAMERA_HEIGHT - 1
 
	if x != camera_x or y != camera_y: fov_recompute = True
 
	(camera_x, camera_y) = (x, y)
 
def to_camera_coordinates(x, y):
	#convert coordinates on the map to coordinates on the screen
	(x, y) = (x - camera_x, y - camera_y)
 
	if (x < 0 or y < 0 or x >= CAMERA_WIDTH or y >= CAMERA_HEIGHT):
		return (None, None)  #if it's outside the view, return nothing
 
	return (x, y)


def is_blocked (x, y):
	try:
		if map[x][y].blocked:
			return True
		
		for object in objects:
			if object.blocks and object.x == x and object.y == y:
				return True
		return False
	except:
		return True

def create_square_room(room):
	global map
	#go through the tiles in the rectangle and make them possible
	for x in range(room.x1 + 1, room.x2):
		for y in range(room.y1 + 1, room.y2):
			try:
				map[x][y].blocked = False
				map[x][y].block_sight = False
			except:
				pass

def create_circle_room(room):
	global map
	r = 3
	
def create_htunnel(x1, x2, y1):
		global map
		for x in range(min(x1,x2), max(x1,x2) + 1):
			map[x][y1].blocked = False
			map[x][y1].block_sight = False

def create_vtunnel(y1,y2,x):
	global map
	for y in range(min(y1,y2), max(y1,y2)+1):
		map[x][y].blocked = False
		map[x][y].block_sight = False

def from_dungeon_level(table):
	for (value, level) in reversed(table):
		if dungeon_level >= level:
			return value
	return 0
def monster_define(monster_name):	
	if monster_name == 'satyr':
		satyr_atk = [club, bite, ram]
		satyr_atk_prob = [5, 3, 2]
		satyr_ai = BasicMonster(100, satyr_atk, satyr_atk_prob)
		satyr_blood = Object(1,1,'~', 'Satyr Blood', libtcod.red)
		satyr_component = creature(blood = 40, trauma = 50, defense = 0, power = 4, speed = 110, xp = 50,  death_function = monster_death, blood_fluid = satyr_blood, drop_dict = drops)
		satyr_description = 'A man shaped creature with the upper body of a man and the lower body of a goat complete with hooves.  Small horns curl up from its forehead.'
		monster = Object(1,1, 's', 'satyr', libtcod.green, description = satyr_description, blocks = True, creature = satyr_component, ai = satyr_ai)
	elif monster_name == 'Myrmidon Fanatic':
		fanatic_atk = [blade,bite]
		fanatic_atk_prob = [6,3]
		fanatic_ai = BasicMonster(80, fanatic_atk, fanatic_atk_prob)
		fanatic_blood = Object(1,1,'~', 'Myrmidon Blood', libtcod.sky)
		drops ={'Bronze Armor': 15, 'L Bronze Grieve':10,'R Bronze Grieve':10, 'Mandiblade':5}
		fanatic_component = creature(blood = 80, trauma = 120, power = 8, defense = 0, speed = 80, xp = 100, death_function = monster_death, blood_fluid = fanatic_blood, drop_dict = drops)
		creature_description = 'This antlike humanoid stares at you with madness in its eyes.  Froth drips form its mandibles as it charges towards you'
		monster = Object(1,1, 'm', 'Myrmidon Fanatic', libtcod.light_blue, description = creature_description, blocks = True, creature = fanatic_component, ai = fanatic_ai)
	elif monster_name == 'Myrmidon Hoplite':
		atk = [spear, bite]
		atk_prob = [4,1]
		creature_ai = BasicMonster(100, atk, atk_prob)
		blood_fluid = Object(1,1,'~', 'Myrmidon Blood', libtcod.sky)
		drops ={'Bronze Armor': 20, 'L Bronze Bracer':10,'R Bronze Bracer':10, 'Spear':40, 'Shield': 30}
		creature_component = creature(blood = 60, trauma = 60, power = 4, defense = 4, speed = 100, xp = 80, death_function = monster_death, blood_fluid = blood_fluid, drop_dict = drops)
		creature_description = "An amalgamation of ant and human.  Two antenna adorn this creature's head above massive compound eyes.  Its mandibles snap together as it hefts its spear over bronze armor."
		monster = Object(1,1, 'm', 'Myrmidon Hoplite', libtcod.orange, description = creature_description, blocks = True, creature = creature_component, ai = creature_ai)
	elif monster_name == 'Myrmidon Workboss':
		atk = [hammer, bite]
		atk_prob = [4,1]
		creature_ai = BasicMonster(110, atk, atk_prob)
		blood_fluid = Object(1,1,'~', 'Myrmidon Blood', libtcod.sky)
		drops ={'Bronze Armor': 30, 'L Bronze Bracer':20,'R Bronze Bracer':20, 'Mandibalde':30}
		creature_component = creature(blood = 120, trauma = 120, power = 10, defense = 8, speed = 110, xp = 200, death_function = monster_death, blood_fluid = blood_fluid, drop_dict = drops)
		creature_description = " Bigger and meaner than the myrmidons you've encountered before, it swings a massive warhammer ith a grace that belies the things massive size"
		monster = Object(1,1, 'M', 'Myrmidon Workboss', libtcod.purple, description = creature_description, blocks = True, creature = creature_component, ai = creature_ai)
	elif monster_name == 'Pompeiitas':
		atk = [fist]
		atk_prob = [1]
		creature_ai = BasicMonster(150, atk, atk_prob)
		blood_fluid = None
		creature_component = creature(blood = 9999, trauma = 100, power = 10, defense = 10, speed = 200, xp = 150, death_function = monster_death, blood_fluid = blood_fluid)
		creature_description = "An ashy simulacrum of a man, the thing shuffles towards you noiselessly.  Its clumsy movements bely an otherwordly and deadly strength."
		monster = Object(1,1, 'p', 'Pompeiitas', libtcod.gray, description = creature_description, blocks = True, creature = creature_component, ai = creature_ai)
	elif monster_name == 'Kalli':
		atk = [club, bite]
		atk_prob = [5,3]
		creature_ai = BasicMonster(90, atk, atk_prob)
		blood_fluid = Object(1,1,'~', 'Kallikantzaros Blood', libtcod.black)
		drops ={'Bandage': 50,'Dagger': 20, 'Club': 20, 'L Leather Guard' :10,'R Leather Guard':10,'R Leather Shoe':10, 'L Leather Shoe':10, 'Leather Cap':20, 'Leather Shirt': 15}
		creature_component = creature(blood = 40, trauma = 30, power = 2, defense = 0, speed = 90, xp = 50, death_function = monster_death, blood_fluid = blood_fluid, drop_dict = drops)
		creature_description = "A tiny humanoid half your height with hairy legs and donkey ears.  It grins at you evilly with a mouth filled with yellow, pointed teeth"
		monster = Object(1,1, 'k', 'Kallikantzaros', libtcod.green, description = creature_description, blocks = True, creature = creature_component, ai = creature_ai)
	return monster

def item_define(item_name, x, y):
	#######Weapons########
	if item_name == 'Dagger':
		weapon_component = Weapon('Right Hand', power_bonus = 1, ratio = .6, speed_mod = .85, damage_mod = .8)
		item = Object(0, 0, '/', 'Dagger', libtcod.sky, weapon=weapon_component)
	elif item_name == 'Club':
		weapon_component = Weapon('Right Hand', power_bonus = 1, ratio = .2, speed_mod = .95, damage_mod = .9)
		item = Object(0, 0, '1', 'Club', libtcod.dark_orange, weapon=weapon_component)
	elif item_name == 'Spear':
		weapon_component = Weapon('Right Hand', power_bonus = 3, ratio = .8, speed_mod = 1, damage_mod = 1)
		item = Object(0, 0, '|', 'Spear', libtcod.orange, weapon=weapon_component)
	elif item_name == 'Sword':
		weapon_component = Weapon('Right Hand', power_bonus = 2, ratio = .6, speed_mod = 1, damage_mod = 1)
		item = Object(x,y,'/','sword', libtcod.sky, weapon = weapon_component)
	elif item_name == 'Warhammer':
		weapon_component = Weapon('Right Hand', power_bonus = 4, ratio = .35, speed_mod = 1.2, damage_mod = 1.1)
		item = Object(x,y,'1','Warhammer', libtcod.sky, weapon = weapon_component)
	elif item_name == 'Mandiblade':
		weapon_component = Weapon('Right Hand', power_bonus = 6, ratio = .9, speed_mod = .9, damage_mod = 1.1)
		item = Object(x,y,'/','sword', libtcod.sky, weapon = weapon_component)
	########comsumables#########
	elif item_name == 'Healing Potion':
		item_component = Item(use_function = cast_heal)
		item = Object(x, y, '!', 'healing potion', libtcod.violet, item = item_component)
	elif item_name == 'Lightning Scroll':
		item_component = Item(use_function = cast_lightning)
		item  = Object(x,y,'!', 'scroll of lightning bolt', libtcod.yellow, item = item_component)
	elif item_name =='Fireball Scroll':
		item_component = Item(use_function = cast_fireball)
		item  = Object(x,y,'!', 'scroll of Fireball', libtcod.red, item = item_component)
	elif item_name == 'Bandage':
		item_component = Item(use_function = bandage)
		item  = Object(x,y,'+', 'Bandages', libtcod.white, item = item_component)
	##########Armor###########
	elif item_name == 'Shield':
		equipment_component = Equipment (slot = 'Left Hand', defense_bonus = 4)
		item = Object(x,y,'[', 'shield', libtcod.darker_orange, equipment = equipment_component)
	#Leather Armor
	elif item_name == 'Leather Shirt':
		equipment_component = Equipment(slot = 'Chest', defense_bonus = 2)
		item = Object(x,y,24,'leather shirt', libtcod.darker_orange, equipment = equipment_component)
	elif item_name == 'L Leather Shoe':
		equipment_component = Equipment(slot = 'Left Leg', defense_bonus = .75)
		item = Object(x,y,'-','Left Leather Shoe', libtcod.darker_orange, equipment = equipment_component)
	elif item_name == 'R Leather Shoe':
		equipment_component = Equipment(slot = 'Right Leg', defense_bonus = .75)
		item = Object(x,y,'-','Right Leather Shoe', libtcod.darker_orange, equipment = equipment_component)
	elif item_name == 'R Leather Guard':
		equipment_component = Equipment(slot = 'Right Arm', defense_bonus = .75)
		item = Object(x,y,'=','Right Leather Arm', libtcod.darker_orange, equipment = equipment_component)
	elif item_name == 'L Leather Guard':
		equipment_component = Equipment(slot = 'Left Arm', defense_bonus = .75)
		item = Object(x,y,'=','Left Leather Guard', libtcod.darker_orange, equipment = equipment_component)
	elif item_name == 'Leather Cap':
		equipment_component = Equipment(slot = 'Head', defense_bonus = 1)
		item = Object(x,y,'^','Leather Cap', libtcod.darker_orange, equipment = equipment_component)
	#Bronze Armor
	elif item_name == 'Bronze Armor':
		equipment_component = Equipment(slot = 'Chest', defense_bonus = 4)
		item = Object(x,y,24,'Bronze Armor', libtcod.brass, equipment = equipment_component)
	elif item_name == 'L Bronze Grieve':
		equipment_component = Equipment(slot = 'Left Leg', defense_bonus = 1)
		item = Object(x,y,'-','Left Bronze Grieve', libtcod.brass, equipment = equipment_component)
	elif item_name == 'R Bronze Grieve':
		equipment_component = Equipment(slot = 'Right Leg', defense_bonus = 1)
		item = Object(x,y,'-','Right Bronze Grieve', libtcod.brass, equipment = equipment_component)
	elif item_name == 'R Bronze Bracer':
		equipment_component = Equipment(slot = 'Right Arm', defense_bonus = 1)
		item = Object(x,y,'=','Right Leather Arm', libtcod.brass, equipment = equipment_component)
	elif item_name == 'L Bronze Bracer':
		equipment_component = Equipment(slot = 'Left Arm', defense_bonus = 1)
		item = Object(x,y,'=','Left Bronze Bracer', libtcod.brass, equipment = equipment_component)
	elif item_name == 'Bronze Helmet':
		equipment_component = Equipment(slot = 'Head', defense_bonus = 2)
		item = Object(x,y,'^','Bronze Helmet', libtcod.brass, equipment = equipment_component)
	#Iron Armor
	elif item_name == 'Iron Breastplate':
		equipment_component = Equipment(slot = 'Chest', defense_bonus = 6)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,24,'Iron Breastplate', libtcod.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Iron Helm':
		equipment_component = Equipment(slot = 'Head', defense_bonus = 3)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,'^','Iron Helm', libtcod.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Left Iron Bracer':
		equipment_component = Equipment(slot = 'Left Arm', defense_bonus = 1.5)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,'=','Left Iron Bracer', libtcod.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Right Iron Bracer':
		equipment_component = Equipment(slot = 'Right Arm', defense_bonus = 1.5)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,'=','Right Iron Bracer', libtcod.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Left Iron Grieve':
		equipment_component = Equipment(slot = 'Left Leg', defense_bonus = 1.5)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,'-','Left Iron Grieve', libtcod.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Right Iron Grieve':
		equipment_component = Equipment(slot = 'Right Leg', defense_bonus = 1.5)
		item_description = 'This is a placeholder description. It can be as long as I want'
		item = Object(x,y,'-','Right Iron Grieve', libtcod.grey, description = item_description, equipment = equipment_component)
	#Steel Armor

	elif item_name == 'STeel Helm':
		equipment_component = Equipment(slot = 'Head', defense_bonus = 5)
		item_description = 'This is made of steel! Neat!'
		item = Object(x,y,'^','STeel Helm', libtcod.dark.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Left Steel Bracer':
		equipment_component = Equipment(slot = 'Left Arm', defense_bonus = 2.5)
		item_description = 'This is made of steel! Neat!'
		item = Object(x,y,'=','Left Steel Bracer', libtcod.dark.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Right Steel Bracer':
		equipment_component = Equipment(slot = 'Right Arm', defense_bonus = 2.5)
		item_description = 'This is made of steel! Neat!'
		item = Object(x,y,'=','Right Steel Bracer', libtcod.dark.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Left Steel Grieve':
		equipment_component = Equipment(slot = 'Left Leg', defense_bonus = 2.5)
		item_description = 'This is made of steel! Neat!'
		item = Object(x,y,'-','Left Steel Grieve', libtcod.dark.grey, description = item_description, equipment = equipment_component)
	elif item_name == 'Right Steel Grieve':
		equipment_component = Equipment(slot = 'Right Leg', defense_bonus = 2.5)
		item_description = 'This is made of steel! Neat!'
		item = Object(x,y,'-','Right Steel Grieve', libtcod.dark.grey, description = item_description, equipment = equipment_component)
	#Miscelanious
	else:
		item_component = Item(use_function = None)
		print "I tried to create a " + item_name
		item = Object(x,y,'#','Ash', libtcod.grey, description= 'Something fucked up and this item turned to ash')
	return item
	print "I tried to create a " + item_name
	
def place_objects(room, map_set = 'dungeon'):
	#random number of monsters
	max_monsters = from_dungeon_level([[1,1],[2,2],[3,4]])
	monster_chances = {}
	if map_set == 'dungeon':
		#monster_chances['satyr'] = 50
		#monster_chances['satyr_squad'] = 30
		monster_chances['Kalli'] = from_dungeon_level([[50,1],[35,3],[10,5], [0,7]])
		monster_chances['Myrmidon Hoplite'] = from_dungeon_level([[15,3],[40,4],[50,5]])
		monster_chances['Myrmidon Fanatic'] = from_dungeon_level([[10,4],[20,6],[25,7]])
		monster_chances['Myrmidon Workboss'] = from_dungeon_level([[15,6],[30,8]])
		monster_chances['Pompeiitas'] = from_dungeon_level([[30,5]])
	num_monsters = libtcod.random_get_int(0,0,max_monsters)
	for i in range(num_monsters):
		choice = random_choice(monster_chances)
		#monster_squad = []
		print choice
		
		monster = monster_define(choice)
		monster.x = libtcod.random_get_int(0, room.x1 + 1, room.x2 - 1)
		monster.y = libtcod.random_get_int(0, room.y1 + 1, room.y2 - 1)
		objects.append(monster)
	
	max_item = from_dungeon_level([[1,1]])
	
	item_chances = {}
	item_chances['Sword']=from_dungeon_level([[5,4]])
	item_chances['Shield']=from_dungeon_level([[15,8]])
	item_chances['Bandage'] = 35
	item_chances['Lightning Scroll'] = from_dungeon_level([[25, 4]])
	item_chances['Fireball Scroll'] =  from_dungeon_level([[25, 6]])
	
	
	num_item = libtcod.random_get_int(0,0,max_item)
	
	for i in range(num_item):
		#choose random spot for item
		x = libtcod.random_get_int(0, room.x1+1, room.x2-1)
		y = libtcod.random_get_int(0, room.y1+1, room.y2-1)
		if not is_blocked(x,y):
			choice = random_choice(item_chances)
			item = item_define(choice, x, y)
			objects.append(item)
			item.send_to_back()

def message(new_msg, color = libtcod.white):
	global game_msgs
	new_msg_lines = textwrap.wrap(new_msg, MSG_WIDTH)
	
	for line in new_msg_lines:
	#if buffer is full, remove the first line to make room for new one
		if len(game_msgs) == MSG_HEIGHT:
			del game_msgs[0]
		
		game_msgs.append( (line, color) )

def make_map(map_set = 'dungeon'):
	global map, objects, dungeon_level, stairs
	
	objects = [player]
	
	map = [[Tile(True)
		for y in range(MAP_HEIGHT) ]
			for x in range(MAP_WIDTH) ]

	rooms = []
	num_rooms = 0
	if map_set == 'dungeon':
		for r in range(MAX_ROOMS):
			#random width and height
			w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
			h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
			#random position without going out of bounds
			x = libtcod.random_get_int(0, 0, MAP_WIDTH - w - 1)
			y = libtcod.random_get_int(0, 0, MAP_HEIGHT - h - 1)

			new_room = rect(x, y, w, h)

			failed = False
			for other_room in rooms:
				if new_room.intersect(other_room):
					failed = True
					break
					
			if not failed:
				#no intersections
				#"paint" it to the map
				create_square_room(new_room)
				(new_x, new_y) = new_room.center()

				if num_rooms == 0:
					player.x = new_x
					player.y = new_y
				else:
					(prev_x, prev_y) = rooms[num_rooms-1].center()
					if libtcod.random_get_int(0,0,1) == 1:
						create_htunnel(prev_x, new_x, new_y)
						create_vtunnel(prev_y, new_y, prev_x)
					else:
						create_vtunnel(prev_y, new_y, new_x)
						create_htunnel(prev_x, new_x, prev_y)
				place_objects(new_room)
				rooms.append(new_room)
				num_rooms += 1
	elif map_set == 'lava_tunnels':
		#random width and height
		w = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
		h = libtcod.random_get_int(0, ROOM_MIN_SIZE, ROOM_MAX_SIZE)
		#random position without going out of bounds
		x = MAP_WIDTH/2
		y = MAP_HEIGHT / 2
		
		new_room = rect(x, y, w, h)
		
		create_square_room(new_room)
		
		(new_x, new_y) = new_room.center()
		
		player.x = new_x
		player.y = new_y
		
		new_room = rect(x, y, w, h)
		
	
		num_tubes = 0
		max_tubes = 10
		found_wall = False
		tunnels = []
		
		test_wallx = new_x
		test_wally = new_y
		direction = libtcod.random_get_int(0,0,3)
		while not found_wall:
			if map[test_wallx][test_wally].blocked:
				found_wall = True
				break
			if direction == 0:
				theta = 90
				test_wally += 1
			elif direction == 1:
				theta = 0
				test_wallx += 1
			elif direction == 2:
				theta = 270
				test_wally -= 1
			elif direction == 3:
				theta = 180
				test_wallx -= 1
		
		startx = test_wallx
		starty = test_wally
		tubes = []
		length = libtcod.random_get_int(0, 10,20)
		tubes.append(tunnel(startx, starty, theta, length))
		for tube in tubes:
			
			endx = tube.endx
			endy = tube.endy
			dice = libtcod.random_get_int(0,0,4)
			
			
			# theta = libtcod.random_get_int(0, 0, 60)
			# length = libtcod.random_get_int(0, 15,25)
			# tunnel_1 = tunnel(endx, endy, theta, length)
			# tubes.append(tunnel_1)
				
			# theta = libtcod.random_get_int(0, -60, 0)
			# length = libtcod.random_get_int(0, 15,25)
			# tunnel_2 = tunnel(endx, endy, theta, length)
			# tubes.append(tunnel_2)
			
			if dice == 0:
				theta = libtcod.random_get_int(0, 0, 60)
				length = libtcod.random_get_int(0, 20,30)
				tunnel_1 = tunnel(endx, endy, theta, length)
				tubes.append(tunnel_1)
				
			theta = libtcod.random_get_int(0, -60, 0)
			length = libtcod.random_get_int(0, 20,30)
			tunnel_2 = tunnel(endx, endy, theta, length)
			tubes.append(tunnel_2)
			
			num_tubes += 1
			if num_tubes > max_tubes:
				break
		rooms = []
		for tube in tubes:
			tube.dig_tunnel()
			dirct = libtcod.random_get_int(0,1,tube.length)
			r = tube.length
			theta = tube.theta
			x = math.floor(tube.x + r * math.cos(theta))
			y = math.floor(tube.y + r * math.sin(theta))
			
			new_room = square_from_center(x,y,r/6)
			
			failed = False
			
			for other_room in rooms:
				if new_room.intersect(other_room):
					failed = True
					break
			if not failed:
				create_square_room(new_room)
				place_objects(new_room)
				rooms.append(new_room)
			
	
	exit_room = rooms[-1]
	
	center = exit_room.center()
	x = center[0]
	y = center[1]
	stairs = Object(x, y, '<', 'stairs', libtcod.white, always_visible = True)
	objects.append(stairs)
	stairs.send_to_back()

def damage_description(object):
	#Will create descriptions of damage dealt to a creature.  If it is the player, monster_name will be
	#replaced with "You" for obvious reasons. Output will be an array that goes [blood, wounds, trauma, breath]
	#Breath is unused but at least its there for now
	if object.creature is not None: #obviously if its not a creature, it'll just return nothing
		creature = object.creature #Creature component of requested object
		damage_descriptions = ['Something', 'went', 'terribly', 'wrong'] #if you see any of this text, you've goofed
		blood_percent  =  creature.blood / creature.max_blood
		wound_percent  =  creature.wounds / creature.max_blood #Basically used as an indicator of turns until you bleed out
		trauma_percent =  creature.trauma / creature.max_trauma
		if object.name is 'player':
			#blood mssage
			if blood_percent <= 0:
				damage_descriptions[0] = "You've died"
			elif blood_percent <.10:
				damage_descriptions[0] = "The Darkness is creeping in..."
			elif blood_percent < .25:
				damage_descriptions[0] = "Your vision is fading"
			elif blood_percent < .50:
				damage_descriptions[0] = "You've lost a lot of blood"
			elif blood_percent < .85:
				damage_descriptions[0] = "You're pretty hurt"
			elif blood_percent < .95:
				damage_descriptions[0] = "You've lost a little of blood"
			else:
				damage_descriptions[0] = "You're perfectly healthy"
			#Trauma Message
			if trauma_percent <= 0:
				damage_descriptions[2] = "You've been knocked unconscious"
			elif trauma_percent <.10:
				damage_descriptions[2] = "You can barely stand!"
			elif trauma_percent < .25:
				damage_descriptions[2] = "You struggle to stay upright"
			elif trauma_percent < .50:
				damage_descriptions[2] = "You're feeling woozy"
			elif trauma_percent < .85:
				damage_descriptions[2] = "You've taken a beating"
			elif trauma_percent < .95:
				damage_descriptions[2] = "You're slightly bruised"
			else:
				damage_descriptions[2] = "You feel fine"
			#Wounds Message
			if wound_percent <.01:
				damage_descriptions[1] = "You are not Wounded."
			elif wound_percent < .05:
				damage_descriptions[1] = "You have a couple of scratches"
			elif wound_percent < .10:
				damage_descriptions[1] = "You're cut up"
			elif wound_percent < .20:
				damage_descriptions[1] = "You're bleeding badly"
			else:
				damage_desciptions[1] = "You're bleeding profusely!!"
		return damage_descriptions
	return None #oops not a creature

def next_level():
	global dungeon_level
	
	message('you descend deeper into the island...', libtcod.light_red)
	player.creature.blood = player.creature.max_blood
	player.creature.trauma = player.creature.max_trauma
	dungeon_level += 1
	make_map('dungeon')
	initialize_fov()
	
	
def player_move_or_attack(dx, dy):
	global fov_recompute
	
	x = player.x + dx
	y = player.y - dy
	
	target = None
	for object in objects:
		if object.creature and object.x == x and object.y ==y:
			target = object
			break
	
	if target is not None:
		weapon_attack(player, target)
	else:
		player.move(dx,dy)
		fov_recompute = True

def player_pick_up():
	#pick up an item
	#Create list of items in the same square as player
	#if list is 1 long, then pick up that one item
	#if list is longer, create menu to pick up things on square
	
	on_square= []
	on_square_name = []
	
	for object in objects:  #look for an item in the player's tile
		if object.x == player.x and object.y == player.y and object.item:
			
			on_square.append(object)
			on_square_name.append(object.name)
	if len(on_square)==0:
		return 'Trying and failing to pick something up',0
	elif len(on_square) == 1:
		#Maybe someday items will be picked up at a speed depending on their weight
		objects.remove(on_square[0])
		return 'picked up' , 10
	else:
		desired_items = menu('please help', on_square_name, INVENTORY_WIDTH)
		
		print desired_item.name

		
		
def get_name_under_cursor():
	global lk_cursor

	if game_state == 'looking' or game_state == 'aiming':
		(x,y) = (lk_cursor.x, lk_cursor.y)
		
		names = [obj.name for obj in objects
			if (obj.x == x and obj.y == y and libtcod.map_is_in_fov(fov_map, obj.x, obj.y)) and obj.name != 'lk_cursor']
		names.remove(lk_cursor.name)
		names = ', '.join(names)
		return names.capitalize()
	
		
def handle_keys():
	global playerx, playery, fov_recompute, game_state
	global lk_cursor, objects
	
	key = libtcod.console_wait_for_keypress(True)
	key_char = chr(key.c)
	
	if key.vk == libtcod.KEY_ENTER and key.lalt:
		libtcod.console_set_fullscreen(not libtcod.console_is_fullscreen())
		
	
	if key.vk == libtcod.KEY_F1:
		next_level()
	
	if game_state == 'looking':
		if key.vk == libtcod.KEY_KP8 or key.vk == libtcod.KEY_UP:
			lk_cursor.move(0,1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP2 or key.vk == libtcod.KEY_DOWN:
			lk_cursor.move(0, -1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP6 or key.vk == libtcod.KEY_RIGHT:
			lk_cursor.move(1, 0)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP4 or key.vk == libtcod.KEY_LEFT:
			lk_cursor.move(-1, 0)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP7:
			lk_cursor.move(-1, 1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP9:
			lk_cursor.move(1, 1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP1:
			lk_cursor.move(-1, -1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP3:
			lk_cursor.move(1, -1)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_KP4:
			lk_cursor.move(-1, 0)
			return 'looking_around', 0
		elif key.vk == libtcod.KEY_ENTER or key.vk == libtcod.KEY_KPENTER:
			for object in objects:
				if object.x == lk_cursor.x and object.y == lk_cursor.y and object.description is not ' ':
					msgbox(object.description)
		elif key.c == ord('x') or key.vk == libtcod.KEY_ESCAPE:
			game_state = 'playing'
			message('You get back to business')
			objects.remove(lk_cursor)
			return 'didnt-take-turn' , 0
			
	if key.vk == libtcod.KEY_ESCAPE:
		return 'exit' , 0	
		
	if game_state == 'playing': 
		if key.vk == libtcod.KEY_KP8 or key.vk == libtcod.KEY_UP:
			player_move_or_attack(0, 1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP2 or key.vk == libtcod.KEY_DOWN:
			player_move_or_attack(0, -1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP6 or key.vk == libtcod.KEY_RIGHT:
			player_move_or_attack(1, 0)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP4 or key.vk == libtcod.KEY_LEFT:
			player_move_or_attack (-1, 0)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP7:
			player_move_or_attack (-1, 1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP9:
			player_move_or_attack (1, 1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP1:
			player_move_or_attack(-1, -1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP3:
			player_move_or_attack (1, -1)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP4:
			player_move_or_attack (-1, 0)
			return 'took_turn', player.creature.speed
		elif key.vk == libtcod.KEY_KP5:
			return 'waited', 50
			pass
		else:
			#test for other keys
			
		
			if key_char == ',':
				#go down stairs
				if stairs.x == player.x and stairs.y == player.y:
					next_level()
 
			if key_char == 'g':
						return player_pick_up()
			if key_char == 'i':
				chosen_item = inventory_menu('Press the key next to an item to use it. \n')
				if chosen_item is not None:
					chosen_item.use()
					return 'used-item', 15
					
			if key_char == 'd':
				chosen_item = inventory_menu ('Press the key next to an item to drop it.')
				if chosen_item is not None:
					chosen_item.drop()
					return 'dropped-item', 10 
					
			if key.c == ord('x'):
				if game_state == 'playing':
					game_state = 'looking'
					message('You take a gander at your surrounding')
					lk_cursor = Object(player.x, player.y, 'X', 'Cursor', libtcod.yellow, ghost = True, always_visible = True)
					objects.insert(0,lk_cursor)
					return 'didnt-take-turn' , 0
	return 'didnt-take-turn' , 0
		
def render_bar(x, y, total_width, name, value, maximum, bar_color, back_color):
	#render a bar (HP, experience, etc). first calculate the width of the bar
	bar_width = int(float(value) / maximum * total_width)
 
	#render the background first
	libtcod.console_set_default_background(panel, back_color)
	libtcod.console_rect(panel, x, y, total_width, 1, False, libtcod.BKGND_SCREEN)
 
	#now render the bar on top
	libtcod.console_set_default_background(panel, bar_color)
	if bar_width > 0:
		libtcod.console_rect(panel, x, y, bar_width, 1, False, libtcod.BKGND_SCREEN)
 
	#finally, some centered text with the values
	libtcod.console_set_default_foreground(panel, libtcod.white)
	libtcod.console_print_ex(panel, x + total_width / 2, y, libtcod.BKGND_NONE, libtcod.CENTER,
		name + ': ' + str(value) + '/' + str(maximum))

def render_panel_text(x, y, words, text_color):
	libtcod.console_set_default_foreground(panel, text_color)
	libtcod.console_print_ex(panel, x, y, libtcod.BKGND_NONE, libtcod.LEFT, words)
	

def render_all():
	global fov_map, color_dark_wall, color_light_wall
	global color_dark_ground, color_light_ground
	global fov_recompute, objects, con
	
	
	
	move_camera(player.x, player.y)
	
	if fov_recompute:
		#recompute FOV if needed (the player moved or something)
		fov_recompute = False
		libtcod.map_compute_fov(fov_map, player.x, player.y, TORCH_RADIUS, FOV_LIGHT_WALLS, FOV_ALGO)
		libtcod.console_clear(con)
		
		#go through all tiles, and set their background color according to the FOV
		for y in range(CAMERA_HEIGHT):
			for x in range(CAMERA_WIDTH):
				(map_x, map_y) = (camera_x + x, camera_y + y)
				visible = libtcod.map_is_in_fov(fov_map, map_x, map_y)
 
				wall = map[map_x][map_y].block_sight
				if not visible:
					#if it's not visible right now, the player can only see it if it's explored
					if map[map_x][map_y].explored:
						if wall:
							libtcod.console_set_char_background(con, x, y, color_dark_wall, libtcod.BKGND_SET)
						else:
							libtcod.console_set_char_background(con, x, y, color_dark_ground, libtcod.BKGND_SET)
				else:
					#it's visible
					if wall:
						libtcod.console_set_char_background(con, x, y, color_light_wall, libtcod.BKGND_SET )
					else:
						libtcod.console_set_char_background(con, x, y, color_light_ground, libtcod.BKGND_SET )
					#since it's visible, explore it
					map[map_x][map_y].explored = True
	#draw all objects in the list
	
	for object in objects:
		if object != player:
			object.draw()
			
	player.draw()
	
	if game_state == 'looking' or game_state == 'aiming':
		lk_cursor.draw()
		
	
	
	#prepare to render the GUI panel
	libtcod.console_set_default_background(panel, libtcod.black)
	libtcod.console_clear(panel)
	
	y = 1
	#At some point I need to fix this so that there is more room for messages. (See archives button?  Either way, this is a band aid)
	for (line, color) in game_msgs:
		libtcod.console_set_default_foreground(panel, color)
		libtcod.console_print_ex(panel, MSG_X, y, libtcod.BKGND_NONE, libtcod.LEFT, line)
		y += 1
		
	#show the player's stats
	
	libtcod.console_set_default_foreground(panel, libtcod.white)
	
	player_damage = damage_description(player)
	
	libtcod.console_print_ex(panel, 1, 1, libtcod.BKGND_NONE, libtcod.LEFT, player_damage[0]) #Blood
	
	libtcod.console_print_ex(panel,1,2,libtcod.BKGND_NONE, libtcod.LEFT, player_damage[1]) #Trauma
	
	libtcod.console_print_ex(panel, 1,3, libtcod.BKGND_NONE, libtcod.LEFT, player_damage[2])
	
	#render_bar(1, 1, BAR_WIDTH, 'Blood', player.creature.blood, player.creature.max_blood,
	#	libtcod.light_red, libtcod.darker_red)
	#render_bar(1, 2, BAR_WIDTH, 'Trauma', player.creature.trauma, player.creature.max_trauma,
	#	libtcod.darker_grey, libtcod.darkest_grey)
	render_bar(1, 4, BAR_WIDTH, 'Exp', player.creature.xp, 200 + player.level * 150,
		libtcod.light_green, libtcod.darker_green)
	#libtcod.console_print_ex(panel, 1, 4, libtcod.BKGND_NONE, libtcod.LEFT, 'Wounds: ' + str(player.creature.wounds))
	
	libtcod.console_print_ex(panel, 1, 5, libtcod.BKGND_NONE, libtcod.LEFT, 'Dungeon level: ' + str(dungeon_level))
	if game_state == 'looking' or  game_state == 'aiming':
		
		libtcod.console_set_default_foreground(panel, libtcod.light_gray)
		libtcod.console_print_ex(panel, 1, 0, libtcod.BKGND_NONE, libtcod.LEFT, get_name_under_cursor())

	#blit the contents of "panel" to the root console
	libtcod.console_blit(con, 0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, 0, 0, 0)
	libtcod.console_blit(panel, 0, 0, SCREEN_WIDTH, PANEL_HEIGHT, 0, 0, PANEL_Y)
	
	libtcod.console_flush()
	for object in objects:
		object.clear()


def msgbox(text, width=50):
	menu(text, [], width)  #use menu() as a sort of "message box"

def check_level_up():
	level_up_xp = 200 + player.level * 150
	if player.creature.xp >= level_up_xp:
		player.level += 1
		player.creature.xp -= level_up_xp
		message ('Your skills improve and you feel invigorated!')
		
		choice = None
		while choice == None:
			choice = menu('level up!  Choose a state to raise\n',
				['Body (+10 Blood and Trauma, from '+ str(player.creature.max_blood) +')',
				'Strength (+1 to attack damage', 'Agility (move a little faster)', 'Mind(does nothing yet)'], 40)
			if choice == 0:
				player.creature.max_blood += 10
				player.creature.blood += 10
				player.creature.max_trauma += 10
				player.creature.trauma += 10
			elif choice == 1:
				player.creature.power += 1
			elif choice == 2:
				player.creature.speed -= 3
			

def random_choice_index(chances):
	dice = libtcod.random_get_int(0,1,sum(chances))
	
	running_sum = 0
	choice = 0
	for w in chances:
		running_sum += w
		
		if dice <= running_sum:
			return choice
		choice += 1
		
def random_choice(chances_dict):
	chances = chances_dict.values()
	strings = chances_dict.keys()
	return strings[random_choice_index(chances)]
			
def main_menu():
	
	initialize()
	while not libtcod.console_is_window_closed():
		#show the background image, at twice the regular console resolution
		#libtcod.image_blit_2x(img, 0, 0, 0)
		libtcod.console_set_default_foreground(0,libtcod.light_yellow)
		libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT / 2-4, libtcod.BKGND_NONE, libtcod.CENTER, 'ATLANTIS ARISEN' )
		libtcod.console_print_ex(0, SCREEN_WIDTH/2, SCREEN_HEIGHT-2, libtcod.BKGND_NONE, libtcod.CENTER, 'By Carrotz')
		choice = menu('', ['Play a new game', 'continue last game', 'Quit'], 24)
		
		if choice == 0:
			new_game()
			play_game()
		elif choice == 1:
			try:
				load_game()
			except:
				msgbox('\n No saved game to load.\n', 24)
				continue
			play_game()
		elif choice == 2:
			break
	
def new_game():
	global player, inventory, game_msgs, game_state, dungeon_level
	
	inventory = []
	game_msgs = []
	
	dungeon_level = 1
	
	creature_component = creature(blood = 2000, trauma = 200, defense = 0, power = 6, speed = 100, xp = 0, death_function = player_death)
	player = Object(25, 23, '@', 'player',  libtcod.white,"It's you, you dummy, who did you think it was?", blocks = True, creature = creature_component)
	
	player.level = 1
	
	obj = item_define('Dagger', 1, 1)
	inventory.append(obj)
	obj.equipment.equip()
	obj.always_visible = True
	
	make_map()
	initialize_fov()
	
	
	game_state = 'playing'
	
	
	
	

def initialize_fov():
	global fov_recompute, fov_map
	fov_recompute = True
	libtcod.console_clear(con)
	fov_map = libtcod.map_new(MAP_WIDTH, MAP_HEIGHT)
	for y in range(MAP_HEIGHT):
		for x in range(MAP_WIDTH):
			libtcod.map_set_properties(fov_map, x, y, not map[x][y].block_sight, not map[x][y].blocked)

def play_game():
	global key, con
	global camera_x, camera_y
	
	(camera_x, camera_y) = (0, 0)
	
	game_state = 'playing'
	
	save_timer = 10
	key = libtcod.Key()
	while not libtcod.console_is_window_closed():
		#print game_state
		player_state = damage_description(player)
		print player_state
		render_all()
		if game_state is not 'Unconscious':
			player_action = handle_keys()
		
		if player_action[0] == 'exit':
			save_game()
			break
		if game_state == 'playing':
			for object in objects:
				if object.ai:
					object.ai.take_turn(time = player_action[1])
			player.creature.bleed(time = player_action[1])
			if player.creature.trauma <= 0:
				game_state = 'Unconscious'
			check_level_up()

		if game_state == 'Unconscious':
			time.sleep(1)
			print 'sleeping'
			player_action = ['passed out', 50]
			for object in objects:
				if object.ai:
					object.ai.take_turn(time = player_action[1])
			player.creature.bleed(time = 50)
			if player.creature.trauma >= 10:
				game_state = 'playing'

	
def initialize():
	global con, panel, game_msgs, dungeon_level
	
	game_msgs=[]
	
	libtcod.console_set_custom_font('arial12x12.png', libtcod.FONT_TYPE_GREYSCALE | libtcod.FONT_LAYOUT_TCOD)
	libtcod.console_init_root(SCREEN_WIDTH, SCREEN_HEIGHT, 'python/libtcod tutorial', False)
	con = libtcod.console_new(SCREEN_WIDTH, SCREEN_HEIGHT)

	panel = libtcod.console_new(SCREEN_WIDTH, PANEL_HEIGHT)
	libtcod.sys_set_fps(20)
	
	fov_recompute = True

	player_action = None

	panel = libtcod.console_new(SCREEN_WIDTH, PANEL_HEIGHT)

	message('Welcome to Atlantis', libtcod.red)

def save_game():
	#open a new empty shelve (possibly overwriting an old one) to write the game data
	file = shelve.open('savegame', 'n')
	file['map'] = map
	file['objects'] = objects
	file['player_index'] = objects.index(player)  #index of player in objects list
	file['inventory'] = inventory
	file['game_msgs'] = game_msgs
	file['game_state'] = game_state
	file['stairs_index'] = objects.index(stairs)
	file['dungeon_level'] = dungeon_level
	file.close()
	
def load_game():
	#open the previously saved shelve and load the game data
	global map, objects, player, stairs, inventory, game_msgs, game_state, dungeon_level
 
	file = shelve.open('savegame', 'r')
	map = file['map']
	objects = file['objects']
	player = objects[file['player_index']]  #get index of player in objects list and access it
	inventory = file['inventory']
	game_msgs = file['game_msgs']
	game_state = file['game_state']
	stairs = objects[file['stairs_index']]
	dungeon_level = file['dungeon_level']
	file.close()
 
	initialize_fov()
	
main_menu()

