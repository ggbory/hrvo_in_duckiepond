#!/bin/bash -e
SHORE_IP="192.168.2.105"
SHORE_PORT="9000"

VEH_NAME1="BRIAN"
VEH_IP1="192.168.2.102"
VEH_PORT1="9100"

VEH_NAME2="MONICA"
VEH_IP2="192.168.2.112"
VEH_PORT2="9200"

COMMUNITY="shoreside"

#-------------------------------------------------------
#  Part 1: Check for and handle command-line arguments
#-------------------------------------------------------
TIME_WARP=1
echo "SHORE_IP = " $SHORE_IP ", VEH_IP1 = " $VEH_IP1 ", VEH_IP2 = " $VEH_IP2
echo "SHORE_PORT = " $SHORE_PORT ", VEH_PORT1 = " $VEH_PORT1 ", VEH_PORT2 = " $VEH_PORT2

#-------------------------------------------------------
#  Part 2: Launch the processes
#-------------------------------------------------------
nsplug shoreside.moos duckiepond_${COMMUNITY}.moos -f  \
    SHORE_PORT=$SHORE_PORT  SHORE_IP=$SHORE_IP \
    VEH_IP1=$VEH_IP1 VEH_IP2=$VEH_IP2 \
    VEH_PORT1=$VEH_PORT1 VEH_PORT2=$VEH_PORT2 \
    VEH_NAME1=$VEH_NAME1 VEH_NAME2=$VEH_NAME2


printf "Launching the %s MOOS Community (WARP=%s) \n"  duckiepond_${COMMUNITY} $TIME_WARP
pAntler duckiepond_${COMMUNITY}.moos --MOOSTimeWarp=$TIME_WARP >& /dev/null &
uMAC -t duckiepond_${COMMUNITY}.moos

printf "Killing all processes ... \n"
kill %1 
mykill
printf "Done killing processes.   \n"
