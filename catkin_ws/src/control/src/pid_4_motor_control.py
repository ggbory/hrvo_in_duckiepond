#!/usr/bin/env python
import numpy as np
import cv2
import roslib
import rospy
import tf
import struct
import math
import time
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseArray, Pose, PoseStamped, Point
from visualization_msgs.msg import Marker, MarkerArray
from nav_msgs.msg import OccupancyGrid, MapMetaData, Odometry
import rospkg
from dynamic_reconfigure.server import Server
from control.cfg import pos_PIDConfig, ang_PIDConfig
from duckiepond.msg import VelocityVector
from std_srvs.srv import SetBool, SetBoolResponse

from PID import PID_control

class Robot_PID():
	def __init__(self):
		self.node_name = rospy.get_name()
		self.dis4constV = 5.0 # Distance for constant velocity
		self.max_dis_ratiao = 1
		self.pos_ctrl_max = 1
		self.pos_ctrl_min = -1
		self.pos_station_max = 0.8
		self.pos_station_min = -0.8
		self.cmd_ctrl_max = 1
		self.cmd_ctrl_min = -1
		self.station_keeping_dis = 3.5 # meters
		self.frame_id = 'map'
		self.is_station_keeping = False
		self.stop_pos = []
		self.final_goal = None # The final goal that you want to arrive
		self.goal = self.final_goal
		self.heading = 0
		rospy.loginfo("[%s] Initializing " %(self.node_name))


		# Param
		self.sim  = rospy.get_param('sim', False)
		self.tune  = rospy.get_param('tune', True)

		self.sub_goal = rospy.Subscriber("/move_base_simple/goal", PoseStamped, self.goal_cb, queue_size=1)
		rospy.Subscriber('localization_gps_imu/odometry', Odometry, self.odom_cb, queue_size = 1, buff_size = 2**24)

		if self.sim:
			from duckiepond_vehicle.msg import UsvDrive	
			self.pub_cmd = rospy.Publisher("cmd_drive", UsvDrive, queue_size = 1)
		else:
			self.pub_cmd = rospy.Publisher("cmd_drive", VelocityVector, queue_size = 1)

		self.pub_goal = rospy.Publisher("goal_point", Marker, queue_size = 1)
		self.station_keeping_srv = rospy.Service("station_keeping", SetBool, self.station_keeping_cb)

		if self.tune:
			self.pos_control = PID_control("Position")
			self.ang_control = PID_control("Angular")

			self.ang_station_control = PID_control("Angular_station")
			self.pos_station_control = PID_control("Position_station")

			self.pos_srv = Server(pos_PIDConfig, self.pos_pid_cb, "Position")
			self.ang_srv = Server(ang_PIDConfig, self.ang_pid_cb, "Angular")
			self.pos_station_srv = Server(pos_PIDConfig, self.pos_station_pid_cb, "Angular_station")
			self.ang_station_srv = Server(ang_PIDConfig, self.ang_station_pid_cb, "Position_station")

			self.initialize_PID()
		else:
			print 'no working...'

	def odom_cb(self, msg):
		self.frame_id = msg.header.frame_id
		robot_position = [msg.pose.pose.position.x, msg.pose.pose.position.y]
		if not self.is_station_keeping:
			self.stop_pos = [msg.pose.pose.position.x, msg.pose.pose.position.y]
		quat = (msg.pose.pose.orientation.x,\
				msg.pose.pose.orientation.y,\
				msg.pose.pose.orientation.z,\
				msg.pose.pose.orientation.w)
		_, _, yaw = tf.transformations.euler_from_quaternion(quat)

		if self.goal is None: # if the robot haven't recieve any goal
			return

		#yaw = yaw + np.pi/2
		goal_vector = self.get_distance(robot_position, self.goal)
		goal_angle = self.get_goal_angle(yaw, robot_position, self.goal)
		goal_distance = math.sqrt(goal_vector[0]**2 +  goal_vector[1]**2)
		

		if goal_distance < self.station_keeping_dis or self.is_station_keeping:
			rospy.loginfo("Station Keeping")
			head_angle = np.degrees(yaw) - self.heading
			pos_x_output,pos_y_output, ang_output = self.station_keeping(head_angle,goal_distance, goal_angle)
		else:
			rospy.loginfo("Navigating")
			head_angle = goal_angle
			pos_x_output,pos_y_output, ang_output = self.control(head_angle,goal_distance, goal_angle)

		if self.sim:
			cmd_msg = UsvDrive()
		else:
			cmd_msg = VelocityVector()
		
		cmd_msg.x = self.cmd_constarin(pos_x_output)
		cmd_msg.y = self.cmd_constarin(pos_y_output)
		cmd_msg.angular = self.cmd_constarin(ang_output)
		print("heading %f"%self.heading)
		print("angular %f" %cmd_msg.angular)
		self.pub_cmd.publish(cmd_msg)
		self.publish_goal(self.goal)

	def control(self, head_angle,goal_distance, goal_angle):
		self.pos_control.update(goal_distance)
		dis_ratiao = -self.pos_control.output/self.dis4constV
		dis_ratiao = max(min(dis_ratiao,self.max_dis_ratiao),0)
		print("dis ratiao%f"%dis_ratiao)

		pos_x_output = math.sin(math.radians(goal_angle))
		pos_y_output = math.cos(math.radians(goal_angle))
		pos_x_output = self.pos_constrain(pos_x_output * dis_ratiao)
		pos_y_output = self.pos_constrain(pos_y_output * dis_ratiao)
		
		# -1 = -180/180 < output/180 < 180/180 = 1
		self.ang_control.update(head_angle)
		ang_output = self.ang_control.output/180. * -1
		return pos_x_output,pos_y_output, ang_output

	def station_keeping(self, head_angle,goal_distance, goal_angle):
		self.pos_station_control.update(goal_distance)
		dis_ratiao = -self.pos_station_control.output/self.dis4constV
		dis_ratiao = max(min(dis_ratiao,self.max_dis_ratiao),0)
		print("dis ratiao%f"%dis_ratiao)

		pos_x_output = math.sin(math.radians(goal_angle))
		pos_y_output = math.cos(math.radians(goal_angle))
		pos_x_output = self.pos_constrain(pos_x_output * dis_ratiao)
		pos_y_output = self.pos_constrain(pos_y_output * dis_ratiao)

		# -1 = -180/180 < output/180 < 180/180 = 1
		self.ang_station_control.update(head_angle)
		ang_output = self.ang_station_control.output/180. * -1
		return pos_x_output,pos_y_output, ang_output

	def goal_cb(self, p):
		self.final_goal = [p.pose.position.x, p.pose.position.y]
		self.goal = self.final_goal
		quat = (p.pose.orientation.x,\
				p.pose.orientation.y,\
				p.pose.orientation.z,\
				p.pose.orientation.w)
		_, _, yaw = tf.transformations.euler_from_quaternion(quat)
		self.heading = np.degrees(yaw)
		

	def station_keeping_cb(self, req):
		if req.data == True:
			self.goal = self.stop_pos
			self.is_station_keeping = True
		else:
			self.goal = self.final_goal
			self.is_station_keeping = False
		res = SetBoolResponse()
		res.success = True
		res.message = "recieved"
		return res

	def cmd_constarin(self, input):
		if input > self.cmd_ctrl_max:
			return self.cmd_ctrl_max
		if input < self.cmd_ctrl_min:
			return self.cmd_ctrl_min
		return input

	def pos_constrain(self, input):
		if input > self.pos_ctrl_max:
			return self.pos_ctrl_max
		if input < self.pos_ctrl_min:
			return self.pos_ctrl_min
		return input

	def pos_station_constrain(self, input):
		if input > self.pos_station_max:
			return self.pos_station_max
		if input < self.pos_station_min:
			return self.pos_station_min
		return input

	def initialize_PID(self):
		self.pos_control.setSampleTime(1)
		self.ang_control.setSampleTime(1)
		self.pos_station_control.setSampleTime(1)
		self.ang_station_control.setSampleTime(1)

		self.pos_control.SetPoint = 0.0
		self.ang_control.SetPoint = 0.0
		self.pos_station_control.SetPoint = 0.0
		self.ang_station_control.SetPoint = 0.0

	def get_goal_angle(self, robot_yaw, robot, goal):
		robot_angle = np.degrees(robot_yaw)
		p1 = [robot[0], robot[1]]
		p2 = [robot[0], robot[1]+1.]
		p3 = goal
		angle = self.get_angle(p1, p2, p3)
		result = angle - robot_angle
		result = self.angle_range(-(result + 90.))
		return result

	def get_angle(self, p1, p2, p3):
		v0 = np.array(p2) - np.array(p1)
		v1 = np.array(p3) - np.array(p1)
		angle = np.math.atan2(np.linalg.det([v0,v1]),np.dot(v0,v1))
		return np.degrees(angle)

	def angle_range(self, angle): # limit the angle to the range of [-180, 180]
		if angle > 180:
			angle = angle - 360
			angle = self.angle_range(angle)
		elif angle < -180:
			angle = angle + 360
			angle = self.angle_range(angle)
		return angle

	def get_distance(self, p1, p2):
		return [p1[0]-p2[0] , p1[1]-p2[1]]

	def publish_goal(self, goal):
		marker = Marker()
		marker.header.frame_id = self.frame_id
		marker.header.stamp = rospy.Time.now()
		marker.ns = "pure_pursuit"
		marker.type = marker.SPHERE
		marker.action = marker.ADD
		marker.pose.orientation.w = 1
		marker.pose.position.x = goal[0]
		marker.pose.position.y = goal[1]
		marker.id = 0
		marker.scale.x = 0.6
		marker.scale.y = 0.6
		marker.scale.z = 0.6
		marker.color.a = 1.0
		marker.color.g = 1.0
		self.pub_goal.publish(marker)

	def pos_pid_cb(self, config, level):
		print("Position: [Kp]: {Kp}   [Ki]: {Ki}   [Kd]: {Kd}\n".format(**config))
		Kp = float("{Kp}".format(**config))
		Ki = float("{Ki}".format(**config))
		Kd = float("{Kd}".format(**config))
		self.pos_control.setKp(Kp)
		self.pos_control.setKi(Ki)
		self.pos_control.setKd(Kd)

		return config

	def ang_pid_cb(self, config, level):
		print("Angular: [Kp]: {Kp}   [Ki]: {Ki}   [Kd]: {Kd}\n".format(**config))
		Kp = float("{Kp}".format(**config))
		Ki = float("{Ki}".format(**config))
		Kd = float("{Kd}".format(**config))
		self.ang_control.setKp(Kp)
		self.ang_control.setKi(Ki)
		self.ang_control.setKd(Kd)
		return config

	def pos_station_pid_cb(self, config, level):
		print("Position: [Kp]: {Kp}   [Ki]: {Ki}   [Kd]: {Kd}\n".format(**config))
		Kp = float("{Kp}".format(**config))
		Ki = float("{Ki}".format(**config))
		Kd = float("{Kd}".format(**config))
		self.pos_station_control.setKp(Kp)
		self.pos_station_control.setKi(Ki)
		self.pos_station_control.setKd(Kd)

		return config

	def ang_station_pid_cb(self, config, level):
		print("Angular: [Kp]: {Kp}   [Ki]: {Ki}   [Kd]: {Kd}\n".format(**config))
		Kp = float("{Kp}".format(**config))
		Ki = float("{Ki}".format(**config))
		Kd = float("{Kd}".format(**config))
		self.ang_station_control.setKp(Kp)
		self.ang_station_control.setKi(Ki)
		self.ang_station_control.setKd(Kd)
		return config

if __name__ == '__main__':
	rospy.init_node('PID_control')
	foo = Robot_PID()
	rospy.spin()
