# sure_petcare
Python library for accessing sure connect petflap

Flap Status:
0 : Unlocked
1 : Keep pets in 
2 : Keep pets out
3 : Locked both ways
4 : Curfew mode

Data types:
 0 : Registered animal entered/left
 6 : Lock status changed, locked in/out or curfew change
 7 : Unregistered animal entered/left
20 : Curfew information

Movement types:
 0 : Manual entry/leaving registration
 4 : Animal looked through the door
 6 : Standard entry/leaving
 8 : Standard entry
11 : Animal left house
13 : Animal left house


Issues : 
Device id generation is currently taken from the mac address, we should proably find out how sure do it in their app.
Currently we update everything, possibly no point if we are only interested in one animal.