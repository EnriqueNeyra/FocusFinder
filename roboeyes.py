# RoboEyes library for MicroPython
#
# See https://github.com/mchobby/micropython-roboeyes
#
# Ported from Arduino FluxGarage RoboEyes for OLED Displays V 1.0.1 
#    https://github.com/FluxGarage/RoboEyes
#
# Copyright (C) 2024 Dennis Hoelscher - www.fluxgarage.com (Arduino Version)
# Copyright (C) 2025 Meurisse Dominique - shop.mchobby.be (MicroPython Version)
#
# GNU General Public License  <https://www.gnu.org/licenses/>.
#
from micropython import const 
from fbutil import FBUtil
from random import randint
import time

# Usage of monochrome display colors
BGCOLOR   = const( 0 ) # background and overlays
FGCOLOR = const( 1 ) # drawings

# For mood type switch
DEFAULT = const( 0 )
TIRED   = const( 1 )
ANGRY   = const( 2 )
HAPPY   = const( 3 )
FROZEN  = const( 4 )
SCARY   = const( 5 )
CURIOUS = const( 6 )

# For turning things on or off
ON  = const( 1 )
OFF = const( 0 )

# For switch "predefined positions"
N  = const( 1 ) # north, top center
NE = const( 2 ) # north-east, top right
E  = const( 3 ) # east, middle right
SE = const( 4 ) # south-east, bottom right
S  = const( 5 ) # south, bottom center
SW = const( 6 ) # south-west, bottom left
W  = const( 7 ) # west, middle left
NW = const( 8 ) # north-west, top left 
# for middle center set "DEFAULT"

class StepData:
	__slots__ = [ "done", "ms_timing", "_lambda" ]

	def __init__( self, owner_seq, ms_timing, _lambda ):
		self.done = False
		self.ms_timing = ms_timing
		self._lambda = _lambda
		self.owner_seq = owner_seq # Sequence

	def update( self, ticks_ms ):
		# Execute the _lambda if applicable then switch the flag
		if self.done:
			return 
		if time.ticks_diff( ticks_ms, self.owner_seq._start ) < self.ms_timing:
			return
		# Execute the _lambda expression (with RoboEyes)
		self._lambda( self.owner_seq.owner ) 
		self.done = True


class Sequence( list ):
	""" a Sequence is a collection of Steps """
	def __init__( self, owner, name ):
		super().__init__()
		self.owner = owner # the RoboEyes class
		self.name = name
		self._start = None

	def step( self, ms_timing, _lambda ):
		# Append a step at a given timing
		_r = StepData( self, ms_timing, _lambda )
		self.append( _r )

	def start( self ):
		# Start the sequence
		self._start = time.ticks_ms()

	def reset( self ):
		# Reset the animation sequence
		self._start = None
		for _step in self:
			_step.done = False

	@property
	def done( self ):
		if self._start == None:
			return True
		return all([ _step.done for _step in self ])

	def update( self, ticks_ms ):
		# Check if we have to execute a step
		if self._start == None:
			return
		[ _step.update( ticks_ms ) for _step in self if _step.done==False ]


class Sequences( list ):
	""" Collection of Sequence (each Sequence made of Steps) """
	def __init__( self, owner ):
		super().__init__()
		self.owner = owner # the RoboEyes class

	def add( self, name  ):
		_r = Sequence( self.owner, name ) # List of steps 
		self.append( _r )
		return _r

	@property
	def done( self ):
		# All sequences are done ?
		return all( [ _seq.done for _seq in self ] )

	def update( self ):
		# Check the various sequences for step to execute
		_ms_ticks = time.ticks_ms()
		[ _seq.update( _ms_ticks ) for _seq in self ]


class RoboEyes():
	def __init__(self, fb, width, height, frame_rate=20, on_show=None, bgcolor=BGCOLOR, fgcolor=FGCOLOR ):
		# on_show : callback event function( robo_eyes ) when framebuffer shoud be sent to display
		assert on_show != None, "on_show event not defined"
		self.fb = fb # FrameBuffer
		self.gfx = FBUtil( fb ) # Extra drawing methods 
		self.on_show = on_show
		self.screenWidth = width # OLED display width, in pixels
		self.screenHeight = height # OLED display height, in pixels
		self.bgcolor = bgcolor
		self.fgcolor = fgcolor

		self.sequences = Sequences( self ) # Collection of sequences

		self.fpsTimer = 0 # For timing the Frames per seconds
		self._position = 0 # see position property. Last known value N,S,E,W, ....
		
		# --[ controlling mood types and expressions ]--
		self._mood = DEFAULT # see mood property. Setting it will update tired,angry,happy,
		self.tired = False
		self.angry = False
		self.happy = False

		self._curious = False   # if true, draw the outer eye larger when looking left or right
		self._cyclops = False   # if true, draw only one eye
		self.eyeL_open = False # left eye opened or closed?
		self.eyeR_open = False # right eye opened or closed?

		# ---------------
		#  Eyes Geometry
		# ---------------
		self.spaceBetweenDefault = 10

		# --[ EYE LEFT - size and border radius ]--
		self.eyeLwidthDefault = 36
		self.eyeLheightDefault = 36
		self.eyeLwidthCurrent = self.eyeLwidthDefault
		self.eyeLheightCurrent = 1 # start with closed eye, otherwise set to eyeLheightDefault
		self.eyeLwidthNext = self.eyeLwidthDefault
		self.eyeLheightNext = self.eyeLheightDefault
		self.eyeLheightOffset = 0
		# Border Radius 
		self.eyeLborderRadiusDefault = 8
		self.eyeLborderRadiusCurrent = self.eyeLborderRadiusDefault
		self.eyeLborderRadiusNext = self.eyeLborderRadiusDefault

		# --[ EYE RIGHT - size and border radius ]--
		self.eyeRwidthDefault = self.eyeLwidthDefault
		self.eyeRheightDefault = self.eyeLheightDefault
		self.eyeRwidthCurrent = self.eyeRwidthDefault
		self.eyeRheightCurrent = 1 # start with closed eye, otherwise set to eyeRheightDefault
		self.eyeRwidthNext = self.eyeRwidthDefault
		self.eyeRheightNext = self.eyeRheightDefault
		self.eyeRheightOffset = 0
		# Border Radius
		self.eyeRborderRadiusDefault = 8
		self.eyeRborderRadiusCurrent = self.eyeRborderRadiusDefault
		self.eyeRborderRadiusNext = self.eyeRborderRadiusDefault

		# --[ EYE LEFT - Coordinates ]--
		self.eyeLxDefault = int( ((self.screenWidth)-(self.eyeLwidthDefault+self.spaceBetweenDefault+self.eyeRwidthDefault))/2 )
		self.eyeLyDefault = int( (self.screenHeight-self.eyeLheightDefault)/2 )
		self.eyeLx = self.eyeLxDefault
		self.eyeLy = self.eyeLyDefault
		self.eyeLxNext = self.eyeLx
		self.eyeLyNext = self.eyeLy

		# --[ EYE RIGHT - Coordinates ]--
		self.eyeRxDefault = self.eyeLx+self.eyeLwidthCurrent+self.spaceBetweenDefault
		self.eyeRyDefault = self.eyeLy
		self.eyeRx = self.eyeRxDefault
		self.eyeRy = self.eyeRyDefault
		self.eyeRxNext = self.eyeRx
		self.eyeRyNext = self.eyeRy

		# --[ BOTH EYES ]--
		# Eyelid top size
		self.eyelidsHeightMax = int(self.eyeLheightDefault/2) # top eyelids max height
		self.eyelidsTiredHeight = 0
		self.eyelidsTiredHeightNext = self.eyelidsTiredHeight
		self.eyelidsAngryHeight = 0
		self.eyelidsAngryHeightNext = self.eyelidsAngryHeight
		# Bottom happy eyelids offset
		self.eyelidsHappyBottomOffsetMax = int(self.eyeLheightDefault/2)+3
		self.eyelidsHappyBottomOffset = 0
		self.eyelidsHappyBottomOffsetNext = 0
		# Space between eyes
		self.spaceBetweenCurrent = self.spaceBetweenDefault
		self.spaceBetweenNext = 10


		# -----------------
		#  Macro Animations
		# -----------------

		# --[ Animation - horizontal flicker/shiver ]--
		self.hFlicker = False
		self.hFlickerAlternate = False
		self.hFlickerAmplitude = 2

		# --[ Animation - vertical flicker/shiver ]--
		self.vFlicker = False
		self.vFlickerAlternate = False
		self.vFlickerAmplitude = 10

		# --[ Animation - auto blinking ]--
		self.autoblinker = False # activate auto blink animation
		self.blinkInterval = 1 # basic interval between each blink in full seconds
		self.blinkIntervalVariation = 4 # interval variaton range in full seconds, random number inside of given range will be add to the basic blinkInterval, set to 0 for no variation
		self.blinktimer = 0 # for organising eyeblink timing

		# --[ Animation - idle mode ]--
		# eyes looking in random directions
		self.idle = False
		self.idleInterval = 1 #  basic interval between each eye repositioning in full seconds
		self.idleIntervalVariation = 3 # interval variaton range in full seconds, random number inside of given range will be add to the basic idleInterval, set to 0 for no variation
		self.idleAnimationTimer = 0 # for organising eyeblink timing

		# --[ Animation - eyes confused ]--
		# eyes shaking left and right
		self._confused = False
		self.confusedAnimationTimer = 0
		self.confusedAnimationDuration = 500
		self.confusedToggle = True

		# --[ Animation - eyes laughing ]--
		# eyes shaking up and down
		self._laugh = False
		self.laughAnimationTimer = 0
		self.laughAnimationDuration = 500
		self.laughToggle = True


		self.clear_display() # clear the display buffer
		self.on_show( self ) # show empty screen
		self.eyeLheightCurrent = 1 # start with closed eyes
		self.eyeRheightCurrent = 1 # start with closed eyes
		self.set_framerate(frame_rate) # calculate frame interval based on defined frameRate		


	# --- GENERAL METHODS ---------------------------------
	#
	# -----------------------------------------------------

	def update( self ):
		# Check if a sequence step must be executed
		self.sequences.update() 
		# Limit drawing updates to defined max framerate
		if time.ticks_diff( time.ticks_ms(), self.fpsTimer ) >= self.frameInterval:
			self.draw_eyes()
			self.fpsTimer = time.ticks_ms()
	

	def clear_display( self ):
		self.fb.fill( self.bgcolor )

	# --- SETTER METHODS ----------------------------------
	#
	# -----------------------------------------------------

	# Calculate frame interval based on defined frameRate
	def set_framerate( self, fps ):
		self.frameInterval = 1000//fps


	def eyes_width( self, leftEye=None, rightEye=None):
		if leftEye!=None:
			self.eyeLwidthNext = leftEye
			self.eyeLwidthDefault = leftEye
		if rightEye!=None:
			self.eyeRwidthNext = rightEye
			self.eyeRwidthDefault = rightEye


	def eyes_height( self, leftEye=None, rightEye=None ):
		if leftEye!=None:
			self.eyeLheightNext = leftEye
			self.eyeLheightDefault = leftEye
		if rightEye!=None:
			self.eyeRheightNext = rightEye
			self.eyeRheightDefault = rightEye


	# Set border radius for left and right eye
	def eyes_radius( self, leftEye=None, rightEye=None):
		if leftEye!=None:
			self.eyeLborderRadiusNext = leftEye
			self.eyeLborderRadiusDefault = leftEye
		if rightEye!=None:
			self.eyeRborderRadiusNext = rightEye
			self.eyeRborderRadiusDefault = rightEye


	# Set space between the eyes, can also be negative
	def eyes_spacing( self, space ):
		self.spaceBetweenNext = space
		self.spaceBetweenDefault = space


	# Set mood expression
	@property
	def mood( self ):
		# Return the last mood
		return self._mood 

	@mood.setter
	def mood( self, mood ):
		# IF old mood was in fickering AND new mood not flinkering THEN
		if ( self._mood in (SCARY,FROZEN) ) and not( mood in (SCARY,FROZEN) ):
			self.horiz_flicker( False )
			self.vert_flicker( False )

		# IF old is curious AND new not curious THEN 
		if self._curious and (mood!=CURIOUS):
			self._curious = False

		if mood ==  TIRED:
			self.tired=True 
			self.angry=False
			self.happy=False
		elif mood ==  ANGRY:
			self.tired=False
			self.angry=True
			self.happy=False
		elif mood == HAPPY:
			self.tired=False
			self.angry=False
			self.happy=True
		elif mood == FROZEN:
			self.tired=False
			self.angry=False
			self.happy=False
			self.horiz_flicker(True, 2)
			self.vert_flicker(False)
		elif mood == SCARY:
			self.tired=True
			self.angry=False
			self.happy=False
			self.horiz_flicker(False)
			self.vert_flicker(True, 2)
		elif mood == CURIOUS:
			self.tired=False
			self.angry=False
			self.happy=False
			self._curious=True
		else:
			self.tired=False
			self.angry=False
			self.happy=False
		self._mood = mood

	# Callable for lamda expression
	def set_mood( self, value ):
		self.mood = value

	# Set predefined position
	@property
	def position( self ):
		return self._position

	@position.setter
	def position( self, direction ):
		if direction == N: # North, top center
			self.eyeLxNext = self.get_screen_constraint_X()//2
			self.eyeLyNext = 0
		elif direction == NE: # North-east, top right
			self.eyeLxNext = self.get_screen_constraint_X()
			self.eyeLyNext = 0
		elif direction == E: # East, middle right
			self.eyeLxNext = self.get_screen_constraint_X()
			self.eyeLyNext = self.get_screen_constraint_Y()//2
		elif direction == SE: # South-east, bottom right
			self.eyeLxNext = self.get_screen_constraint_X()
			self.eyeLyNext = self.get_screen_constraint_Y()
		elif direction == S: # South, bottom center
			self.eyeLxNext = self.get_screen_constraint_X()//2;
			self.eyeLyNext = self.get_screen_constraint_X()
		elif direction == SW: # South-west, bottom left
			self.eyeLxNext = 0
			self.eyeLyNext = self.get_screen_constraint_Y()
		elif direction == W: # West, middle left
			self.eyeLxNext = 0
			self.eyeLyNext = self.get_screen_constraint_Y()//2
		elif direction == NW: # North-west, top left
			self.eyeLxNext = 0
			self.eyeLyNext = 0
		else: # Middle center
			self.eyeLxNext = self.get_screen_constraint_X()//2
			self.eyeLyNext = self.get_screen_constraint_Y()//2
		self._position = direction

	# Callable for lambda expression
	def set_position( self, value ):
		self.position = value


	# Set automated eye blinking, minimal blink interval in full seconds and blink interval variation range in full seconds
	def set_auto_blinker( self, active, interval=None, variation=None):
		self.autoblinker = active
		if interval != None:
			self.blinkInterval = interval
		if variation != None:
			self.blinkIntervalVariation = variation


	# Set idle mode - automated eye repositioning, minimal time interval in full seconds and time interval variation range in full seconds
	def set_idle_mode( self, active, interval=None, variation=None):
		self.idle = active
		if interval != None:
			self.idleInterval = interval
		if variation != None:
			self.idleIntervalVariation = variation

	@property
	def curious( self ):
		return self._curious 

	@curious.setter
	def curious( self, enable ):
		# Set curious mode - the respectively outer eye gets larger when looking left or right
		self._curious = enable

	# Callable for lambda expression
	def set_curious( self, value ):
		self.curious = value

	# Set cyclops mode - show only one eye 
	@property
	def cyclops( self ):
		return self._cyclops

	@cyclops.setter
	def cyclops( self, enabled ):
		self._cyclops = enabled

	# Callable for lambda expression
	def set_cyclops( self, value ):
		self.cyclops = value

	# Set horizontal flickering (displacing eyes left/right)
	def horiz_flicker( self, enable, amplitude=None ):
		self.hFlicker = enable # turn flicker on or off
		if amplitude != None:
			self.hFlickerAmplitude = amplitude # define amplitude of flickering in pixels


	# Set vertical flickering (displacing eyes up/down)
	def vert_flicker( self, enable, amplitude=None ):
		self.vFlicker = enable # turn flicker on or off
		if amplitude  != None:
			self.vFlickerAmplitude = amplitude #  define amplitude of flickering in pixels



	# --- GETTER METHODS ----------------------------------
	#
	# -----------------------------------------------------

	# Returns the max x position for left eye
	def get_screen_constraint_X( self ):
		return self.screenWidth-self.eyeLwidthCurrent-self.spaceBetweenCurrent-self.eyeRwidthCurrent


	# Returns the max y position for left eye
	def get_screen_constraint_Y( self ):
		# using default height here, because height will vary when blinking and in curious mode
		return self.screenHeight-self.eyeLheightDefault 


	# --- BASIC ANIMATION METHODS -------------------------
	#
	# -----------------------------------------------------

	# --[ BLINKING FOR BOTH EYES AT ONCE or separately ]--
	# Close both eyes
	def close( self, left=None, right=None ):
		if (left==None) and (right==None):
			self.eyeLheightNext = 1 # closing left eye
			self.eyeRheightNext = 1 # closing right eye
			self.eyeL_open = False # left eye not opened (=closed)
			self.eyeR_open = False # right eye not opened (=closed)
		else:
			if left != None:
				self.eyeLheightNext = 1 # blinking left eye
				self.eyeL_open = False # left eye not opened (=closed)
			if right != None:
				self.eyeRheightNext = 1 # blinking right eye
				self.eyeR_open = False # right eye not opened (=closed)


	# Open both eyes
	def open( self, left=None, right=None ):
		if (left==None) and (right==None):
			self.eyeL_open = True # left eye opened - if true, draw_eyes() will take care of opening eyes again
			self.eyeR_open = True # right eye opened
		else:
			if left != None:
				self.eyeL_open = True # left eye opened - if true, draw_eyes() will take care of opening eyes again
			if right != None:
				self.eyeR_open = True # right eye opened

	# Trigger eyeblink animation
	def blink( self, left=None, right=None ):
		if (left==None) and (right==None):
			self.close()
			self.open()
		else:
			self.close( left, right )
			self.open( left, right )

	# --- MACRO ANIMATION METHODS -------------------------
	#
	# -----------------------------------------------------

	# Play confused animation - one shot animation of eyes shaking left and right
	def confuse( self ):
		self._confused = True


	# Play laugh animation - one shot animation of eyes shaking up and down
	def laugh( self ):
		self._laugh = True


	def wink( self, left=None, right=None ):
		assert left or right, "Wink must be activated on right or left"
		self.autoblinker = False # activate auto blink animation
		self.idle = False 
		self.blink( left=left, right=right )


	# --- PRE-CALCULATIONS AND ACTUAL DRAWINGS ------------
	#
	# -----------------------------------------------------
	def draw_eyes( self ):

		# --[ PRE-CALCULATIONS - EYE SIZES AND VALUES FOR ANIMATION TWEENINGS ]--

		# Vertical size offset for larger eyes when looking left or right (curious gaze)
		if self._curious :
			if self.eyeLxNext<=10:
				self.eyeLheightOffset=8
			elif ( self.eyeLxNext >= self.get_screen_constraint_X()-10 ) and self._cyclops :
				self.eyeLheightOffset = 8
			else:
				self.eyeLheightOffset = 0 # left eye

			if self.eyeRxNext >= (self.screenWidth-self.eyeRwidthCurrent-10):
				self.eyeRheightOffset = 8
			else:
				self.eyeRheightOffset = 0 # right eye
		else:
			self.eyeLheightOffset = 0 # reset height offset for left eye
			self.eyeRheightOffset = 0 # reset height offset for right eye

		# Left eye height
		self.eyeLheightCurrent = (self.eyeLheightCurrent + self.eyeLheightNext + self.eyeLheightOffset)//2
		self.eyeLy += (self.eyeLheightDefault-self.eyeLheightCurrent)//2 # vertical centering of eye when closing
		self.eyeLy -= self.eyeLheightOffset//2
		# Right eye height
		self.eyeRheightCurrent = (self.eyeRheightCurrent + self.eyeRheightNext + self.eyeRheightOffset)//2
		self.eyeRy += (self.eyeRheightDefault-self.eyeRheightCurrent)//2 # vertical centering of eye when closing
		self.eyeRy -= self.eyeRheightOffset//2


		# Open eyes again after closing them
		if self.eyeL_open :
			if self.eyeLheightCurrent <= (1 + self.eyeLheightOffset):
				self.eyeLheightNext = self.eyeLheightDefault 
		
		if self.eyeR_open :
			if self.eyeRheightCurrent <= (1 + self.eyeRheightOffset):
				self.eyeRheightNext = self.eyeRheightDefault

		# Left eye width
		self.eyeLwidthCurrent = (self.eyeLwidthCurrent + self.eyeLwidthNext)//2
		# Right eye width
		self.eyeRwidthCurrent = (self.eyeRwidthCurrent + self.eyeRwidthNext)//2


		# Space between eyes
		self.spaceBetweenCurrent = (self.spaceBetweenCurrent + self.spaceBetweenNext)//2

		# Left eye coordinates
		self.eyeLx = (self.eyeLx + self.eyeLxNext)//2
		self.eyeLy = (self.eyeLy + self.eyeLyNext)//2
		# Right eye coordinates
		self.eyeRxNext = self.eyeLxNext+self.eyeLwidthCurrent+self.spaceBetweenCurrent # right eye's x position depends on left eyes position + the space between
		self.eyeRyNext = self.eyeLyNext # right eye's y position should be the same as for the left eye
		self.eyeRx = (self.eyeRx + self.eyeRxNext)//2
		self.eyeRy = (self.eyeRy + self.eyeRyNext)//2

		# Left eye border radius
		self.eyeLborderRadiusCurrent = (self.eyeLborderRadiusCurrent + self.eyeLborderRadiusNext)//2
		# Right eye border radius
		self.eyeRborderRadiusCurrent = (self.eyeRborderRadiusCurrent + self.eyeRborderRadiusNext)//2
		  

		# --[ APPLYING MACRO ANIMATIONS ]--

		if self.autoblinker:
			if time.ticks_diff( time.ticks_ms(), self.blinktimer ) >=  0:
				self.blink()
				self.blinktimer = time.ticks_add( time.ticks_ms(), (self.blinkInterval*1000)+(randint(0,self.blinkIntervalVariation)*1000) ) # calculate next time for blinking

		# Laughing - eyes shaking up and down for the duration defined by laughAnimationDuration (default = 500ms)
		if self._laugh:
			if self.laughToggle:
				self.vert_flicker(1, 5)
				self.laughAnimationTimer = time.ticks_ms()
				self.laughToggle = False		
			elif time.ticks_diff( time.ticks_ms(), self.laughAnimationTimer ) >= self.laughAnimationDuration:
				self.vert_flicker(0, 0)
				self.laughToggle = True
				self._laugh = False
		

		# Confused - eyes shaking left and right for the duration defined by confusedAnimationDuration (default = 500ms)
		if self._confused:
			if self.confusedToggle:
				self.horiz_flicker(1, 20)
				self.confusedAnimationTimer = time.ticks_ms()
				self.confusedToggle = False
			elif time.ticks_diff( time.ticks_ms(), self.confusedAnimationTimer) >= self.confusedAnimationDuration :
				self.horiz_flicker(0, 0)
				self.confusedToggle = True
				self._confused= False

		# Idle - eyes moving to random positions on screen
		if self.idle:
			if time.ticks_diff( time.ticks_ms(), self.idleAnimationTimer ) >= 0:
				self.eyeLxNext = randint( 0, self.get_screen_constraint_X() )
				self.eyeLyNext = randint( 0, self.get_screen_constraint_Y() )
				self.idleAnimationTimer = time.ticks_add( time.ticks_ms(), (self.idleInterval*1000)+(randint( 0, self.idleIntervalVariation)*1000) ) # calculate next time for eyes repositioning
			

		# Adding offsets for horizontal flickering/shivering
		if self.hFlicker:
			if self.hFlickerAlternate:
				self.eyeLx += self.hFlickerAmplitude
				self.eyeRx += self.hFlickerAmplitude
			else:
				self.eyeLx -= self.hFlickerAmplitude
				self.eyeRx -= self.hFlickerAmplitude
			self.hFlickerAlternate = not( self.hFlickerAlternate )


		# Adding offsets for horizontal flickering/shivering
		if self.vFlicker:
			if self.vFlickerAlternate:
				self.eyeLy += self.vFlickerAmplitude
				self.eyeRy += self.vFlickerAmplitude
			else:
				self.eyeLy -= self.vFlickerAmplitude
				self.eyeRy -= self.vFlickerAmplitude
			
			self.vFlickerAlternate = not(self.vFlickerAlternate)


		# Cyclops mode, set second eye's size and space between to 0
		if self._cyclops:
			self.eyeRwidthCurrent = 0
			self.eyeRheightCurrent = 0
			self.spaceBetweenCurrent = 0

		# --[ ACTUAL DRAWINGS ]--

		self.clear_display() # start with a blank screen

		# Draw basic eye rectangles
		#   display.fillRoundRect(eyeLx, eyeLy, eyeLwidthCurrent, eyeLheightCurrent, eyeLborderRadiusCurrent, MAINCOLOR); // left eye
		self.gfx.fill_rrect( self.eyeLx, self.eyeLy, self.eyeLwidthCurrent, self.eyeLheightCurrent, self.eyeLborderRadiusCurrent, self.fgcolor ) # left eye
		
		if not self._cyclops:
			# display.fillRoundRect(eyeRx, eyeRy, eyeRwidthCurrent, eyeRheightCurrent, eyeRborderRadiusCurrent, MAINCOLOR); // right eye
			self.gfx.fill_rrect( self.eyeRx, self.eyeRy, self.eyeRwidthCurrent, self.eyeRheightCurrent, self.eyeRborderRadiusCurrent, self.fgcolor )


		# Prepare mood type transitions
		if self.tired:
			self.eyelidsTiredHeightNext = self.eyeLheightCurrent//2 
			self.eyelidsAngryHeightNext = 0
		else:
			self.eyelidsTiredHeightNext = 0
		if self.angry:
			self.eyelidsAngryHeightNext = self.eyeLheightCurrent//2 
			self.eyelidsTiredHeightNext = 0
		else:
			self.eyelidsAngryHeightNext = 0
		if self.happy:
			self.eyelidsHappyBottomOffsetNext = self.eyeLheightCurrent//2
		else:
			self.eyelidsHappyBottomOffsetNext = 0

		# Draw tired top eyelids 
		self.eyelidsTiredHeight = (self.eyelidsTiredHeight + self.eyelidsTiredHeightNext)//2
		if not self._cyclops:
			self.gfx.fill_triangle( self.eyeLx, self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy-1, self.eyeLx, self.eyeLy+self.eyelidsTiredHeight-1, self.bgcolor ) # left eye 
			self.gfx.fill_triangle( self.eyeRx, self.eyeRy-1, self.eyeRx+self.eyeRwidthCurrent, self.eyeRy-1, self.eyeRx+self.eyeRwidthCurrent, self.eyeRy+self.eyelidsTiredHeight-1, self.bgcolor ) # right eye
		else:
			# Cyclops tired eyelids
			self.gfx.fill_triangle( self.eyeLx, self.eyeLy-1, self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy-1, self.eyeLx, self.eyeLy+self.eyelidsTiredHeight-1, self.bgcolor ) # left eyelid half
			self.gfx.fill_triangle( self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy+self.eyelidsTiredHeight-1, self.bgcolor ) # right eyelid half


		# Draw angry top eyelids 
		self.eyelidsAngryHeight = (self.eyelidsAngryHeight + self.eyelidsAngryHeightNext)//2
		if not self._cyclops:
			self.gfx.fill_triangle( self.eyeLx, self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy+self.eyelidsAngryHeight-1, self.bgcolor ) # left eye
			self.gfx.fill_triangle( self.eyeRx, self.eyeRy-1, self.eyeRx+self.eyeRwidthCurrent, self.eyeRy-1, self.eyeRx, self.eyeRy+self.eyelidsAngryHeight-1, self.bgcolor ) # right eye
		else:
			# Cyclops angry eyelids
			self.gfx.fill_triangle( self.eyeLx, self.eyeLy-1, self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy-1, self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy+self.eyelidsAngryHeight-1, self.bgcolor ) # left eyelid half
			self.gfx.fill_triangle( self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy-1, self.eyeLx+self.eyeLwidthCurrent, self.eyeLy-1, self.eyeLx+(self.eyeLwidthCurrent//2), self.eyeLy+self.eyelidsAngryHeight-1, self.bgcolor ) # right eyelid half
		


		# Draw happy bottom eyelids
		self.eyelidsHappyBottomOffset = (self.eyelidsHappyBottomOffset + self.eyelidsHappyBottomOffsetNext)//2
		self.gfx.fill_rrect( self.eyeLx-1, (self.eyeLy+self.eyeLheightCurrent)-self.eyelidsHappyBottomOffset+1, self.eyeLwidthCurrent+2, self.eyeLheightDefault, self.eyeLborderRadiusCurrent, self.bgcolor ) # left eye		
		if not self._cyclops:
			self.gfx.fill_rrect( self.eyeRx-1, (self.eyeRy+self.eyeRheightCurrent)-self.eyelidsHappyBottomOffset+1, self.eyeRwidthCurrent+2, self.eyeRheightDefault, self.eyeRborderRadiusCurrent, self.bgcolor ) # right eye		
		
		self.on_show( self ) # show drawings on display

	# end of drawEyes method