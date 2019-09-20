#!/usr/bin/env python
from __future__ import print_function

import sys
import math
import rospy
import numpy as np
from std_msgs.msg import String
from sensor_msgs.msg import Image
from cv_bridge import CvBridge, CvBridgeError
# sys.path.remove('/opt/ros/kinetic/lib/python2.7/dist-packages')
import cv2
# sys.path.append('/opt/ros/kinetic/lib/python2.7/dist-packages')

min_radius = 10     # board default 10
max_radius = 20     # board default 20
min_dist = min_radius*2

class my_colors:
    colors = np.array([
                    # desk values
                    # ([min], [max])
                    # ("orange", [0, 0, 100], [49, 139, 250]),
                    # ("blue", [20, 0, 0], [150, 50, 50]),
                    # ("white", [60, 60, 60], [255, 255, 255])
                    # board values
                    ("orange", [0, 0, 100], [49, 139, 250]),
                    ("blue", [20, 0, 0], [150, 30, 30]),
                    ("white", [60, 60, 60], [255, 255, 255])
                ],
                dtype=[('name', 'S10'),('lower', '<f8', (3)), ('upper', '<f8', (3))])
    
    @staticmethod
    def get_name_from_bgr(bgr):
        if bgr is not None:
            color_index = np.argwhere(np.all((bgr >= my_colors.colors["lower"]) & (bgr <= my_colors.colors["upper"]), axis=1))
            if len(color_index) != 0:
                return str(my_colors.colors["name"][color_index.reshape(1)[0]])
        return "None"

class stone_class:
    def __init__(self, x=0, y=0, r=0, color=0, distance_from_center=None):
        self.sample_counter = 0
        self.x = x
        self.y = y
        self.r = r
        self.color = color #BGR
        self.color_name = None
        self.distance_from_center = distance_from_center
    
    def get_distance_from_center(self):
        return self.distance_from_center
    
    def set_distance_from_center(self, distance):
        self.distance_from_center = distance

    def set_color_name(self, color_name):
        self.color_name = color_name
    
    def get_color_bgr(self):
        return self.color
    
    def get_color_name(self):
        if self.color_name is None:
            return "None"
        else:
            return self.color_name
    
    def get_center(self):
        return (self.x, self.y)
    
    def refine_stone(self, x, y, r, color):
        self.x = (self.x + x)/2
        self.y = (self.y + y)/2
        # self.x = (self.sample_counter*self.x + x)/(self.sample_counter+1)
        # self.y = (self.sample_counter*self.y + y)/(self.sample_counter+1)
        self.r = (self.sample_counter*self.r+r)/(self.sample_counter+1)
        self.color = (self.sample_counter*self.color+color)/(self.sample_counter+1)
        if self.sample_counter < 10:
            self.sample_counter += 1
        # print("refined stone:")
        # print("\tx = ", str(self.x))
        # print("\ty = ", str(self.y))
        # print("\tr = ", str(self.r))
        # print("\tcolor = ", str(self.color))
        # print("\tsample_counter = ", str(self.sample_counter))


class stone_organizer_class:
    def __init__(self):
        self.stones = []
        self.stone_colors = [
            "orange",
            "blue"
        ]

    def clear(self):
        self.stones = []

    def add_sample(self, x, y, r, color):
        if len(self.stones) != 0:
            x_array = np.asarray(list((s.x for s in self.stones)))
            y_array = np.asarray(list((s.y for s in self.stones)))
            distances = np.sqrt(np.square(x_array - x) + np.square(y_array - y))
            if np.amin(distances) < min_dist:
                self.stones[distances.argmin()].refine_stone(x, y, r, color)
                return True

        self.stones.append(stone_class(x, y, r, color))
        return True

    def set_distance_from_center(self, center):
        for stone in self.stones:
            stone_center = stone.get_center()
            stone.set_distance_from_center(math.sqrt(math.pow(stone_center[0]-center[0], 2) + math.pow(stone_center[1]-center[1], 2)))

    
    def finalize_search(self, center):
        stones_to_remove = []
        for stone in self.stones:
            color_name = my_colors.get_name_from_bgr(stone.get_color_bgr())
            if color_name not in self.stone_colors:
                # this is not a stone
                stones_to_remove.append(stone)
            else:
                stone.set_color_name(color_name)
                self.set_distance_from_center(center)
        for stone in stones_to_remove:
            self.stones.remove(stone)

class board_class:
    def __init__(self, center=None):
        self.center = center
        self.color = None
        self.center_color_name = "white"
        self.sample_counter = 0
        self.error = False
        self.center_found_flag = False
    
    def center_found(self):
        return self.center_found_flag

    def get_error(self):
        return self.error
    
    def get_center(self):
        return self.center
    
    def set_center(self, center):
        self.center = center
    
    def get_color_bgr(self):
        return self.color

    def get_color_name(self):
        return my_colors.get_name_from_bgr(self.color)
    
    def clear(self):
        self.center = None
        self.color = None
        self.sample_counter = 0
        self.error = False
        self.center_found_flag = False
    
    def add_sample(self, x, y, color):
        if my_colors.get_name_from_bgr(color) in self.center_color_name:
            if self.center is not None:
                if math.sqrt(math.pow(self.center[0] - x, 2) + math.pow(self.center[1] - y, 2)) < min_dist:
                    self.center = ((self.sample_counter*self.center[0]+x)/(self.sample_counter+1), (self.sample_counter*self.center[1]+y)/(self.sample_counter+1))
                    self.color = (self.sample_counter*self.color+color)/(self.sample_counter+1)
                    self.sample_counter += 1
                else:
                    print ("Error: SECOND CENTER FOUND")
                    self.error = True
            else:
                self.center = (x, y)
                self.color = color
                self.sample_counter += 1

    
    def finalize_search(self):
        if my_colors.get_name_from_bgr(self.color) in self.center_color_name and not self.error:
            self.center_found_flag = True


class image_converter:

    def __init__(self, iteration_treshold=10, stone_organizer=None, board=None):
        rospy.init_node('image_converter', anonymous=True)
        self.image_pub = rospy.Publisher("my_image_topic",Image, queue_size=10)

        self.bridge = CvBridge()
        self.image_sub = rospy.Subscriber("/camera/rgb/image_raw",Image,self.callback)
        if stone_organizer is None:
            self.so = stone_organizer_class()
        else:
            self.so = stone_organizer
        if board is None:
            self.board = board_class()
        else:
            self.board = board
        self.stone_search_flag = False
        self.center_search_flag = False
        self.iteration = 0
        self.iteration_treshold = iteration_treshold

        # while not rospy.core.is_shutdown():
        #     while not self.board.center_found():
        #         print("Press enter to search for the center")
        #         raw_input()
        #         # input()
        #         self.center_search()
        #         rospy.rostime.wallsleep(1)
        #         while self.center_search_flag:
        #             rospy.rostime.wallsleep(1)

        #     rospy.rostime.wallsleep(1)

        #     while not self.board.get_error and self.board.get_center is not None:
        #         print("Press enter to search for the center")
        #         raw_input()
        #         # input()
        #         self.center_search()

    def clear(self):
        self.iteration = 0
    
    def stone_search(self):
        if not self.stone_search_flag:
            self.so.clear()
            self.clear()
            self.stone_search_flag = True
    
    def stone_search_cb(self, cv_image=None, drawable_image=None):
        
        if self.iteration < self.iteration_treshold:
            self.iteration += 1

            grey_img = cv2.cvtColor(cv_image,cv2.COLOR_BGR2GRAY)
            grey_img = cv2.medianBlur(grey_img,5)
            stones = cv2.HoughCircles(grey_img,cv2.HOUGH_GRADIENT,1,
                                        param1=50,param2=25,minRadius=min_radius,maxRadius=max_radius,minDist=min_dist)
                                        
            if isinstance(stones, np.ndarray):
                stones_nr = len(stones[0])
                stones = np.uint16(np.around(stones))
                print("The number of stones found in iteration " + str(self.iteration) + " is: " + str(stones_nr))
                for stone in stones[0,:]:
                    # draw the outer circle
                    center_x = stone[0]
                    center_y = stone[1]
                    radius = stone[2]

                    color_matrix = cv_image[center_y-(int)(radius/2):center_y+(int)(radius/2),center_x-(int)(radius/2):center_x+(int)(radius/2)]
                    color = np.mean(color_matrix, axis=(0, 1))
                    self.so.add_sample(center_x, center_y, radius, color)
                    
                    cv2.circle(drawable_image,(center_x,center_y),radius,(0,0,255),2)
                    # draw the center of the circle
                    # cv2.circle(colored_img,(center_x,center_y),2,(255,0,0),3)
        else:
            self.stone_search_flag = False
            self.so.finalize_search(self.board.get_center())                    
            rospy.loginfo("Number of stone(s) found: " + str(len(self.so.stones)))

    def center_search(self):
        if not self.center_search_flag:
            self.board.clear()
            self.clear()
            self.center_search_flag = True

    def center_search_cb(self, cv_image=None, drawable_image=None):
        
        if self.iteration < self.iteration_treshold:
            self.iteration += 1

            grey_img = cv2.cvtColor(cv_image,cv2.COLOR_BGR2GRAY)
            grey_img = cv2.medianBlur(grey_img,5)
            circles = cv2.HoughCircles(grey_img,cv2.HOUGH_GRADIENT,1,
                                        param1=50,param2=25,minRadius=min_radius,maxRadius=max_radius,minDist=min_dist)
                                        
            if isinstance(circles, np.ndarray):
                circles_nr = len(circles[0])
                circles = np.uint16(np.around(circles))
                print("The number of circles found in iteration " + str(self.iteration) + " is: " + str(circles_nr))
                for stone in circles[0,:]:
                    # draw the outer circle
                    center_x = stone[0]
                    center_y = stone[1]
                    radius = stone[2]

                    color_matrix = cv_image[center_y-(int)(radius/2):center_y+(int)(radius/2),center_x-(int)(radius/2):center_x+(int)(radius/2)]
                    color = np.mean(color_matrix, axis=(0, 1))
                    self.board.add_sample(center_x, center_y, color)
                    
                    cv2.circle(drawable_image,(center_x,center_y),radius,(0,0,255),2)
                    # draw the center of the circle
                    # cv2.circle(colored_img,(center_x,center_y),2,(255,0,0),3)
        else:
            self.center_search_flag = False
            self.board.finalize_search()                    
            if not self.board.center_found():
                rospy.loginfo("Error in finding the board center, make sure there is no stones on the board and the lighting is optimal")
            else:
                rospy.loginfo("Single center found")
                cv2.circle(drawable_image,self.board.get_center(),2,(0,0,0),2)
                cv2.putText(drawable_image, self.board.get_color_name(), self.board.get_center(), cv2.FONT_HERSHEY_SIMPLEX, 1.0, self.board.get_color_bgr(), lineType=cv2.LINE_AA)

    
    def callback(self,data):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(data, "bgr8")
        except CvBridgeError as e:
            print(e)

        # =============================================
        drawable_image = np.copy(cv_image)

        if self.stone_search_flag:
            self.stone_search_cb(cv_image, drawable_image)
        
        if self.center_search_flag:
            self.center_search_cb(cv_image, drawable_image)

        if self.board.center_found():
            c = self.board.get_center()
            x = c[0]
            y = c[1]

            source = drawable_image
            overlay = None
            alpha = 0.7

            #copy the source image to an overlay
            overlay = np.copy(source)

            # x, y = np.meshgrid(np.linspace(-1,1,320), np.linspace(-1,1,320))
            # d = np.sqrt(x*x+y*y)
            # sigma, mu = 1.0, 0.0
            # g = np.exp(-( (d-mu)**2 / ( 2.0 * sigma**2 ) ) )
            # g = np.float32(g)
            # g = np.floor(g*255)
            # cv2.applyColorMap(g, cv2.COLORMAP_JET)
            # overlay[y-160:y+160, x-160:x+160] = g

            # draw a filled, yellow rectangle on the overlay copy
            x_max = overlay.shape[1]
            y_max = overlay.shape[0]
            cv2.circle(overlay, (x, y), 160, (0,96,255), 2)
            cv2.circle(overlay, (x, y), 100, (0,255,255), 2)
            cv2.circle(overlay, (x, y), 50, (0,255,0), 2)

            # blend the overlay with the source image
            cv2.addWeighted(overlay, alpha, source, 1 - alpha, 0, source);

            cv2.circle(drawable_image, (x, y), 2, (0,128,0), 2)
            # cv2.rectangle(drawable_image, (x-160, y-160), (x+160, y+160), (0,128,0), thickness=2)

        for s in self.so.stones:
            cv2.circle(drawable_image,s.get_center(),2,(0,0,0),3)
            cv2.circle(drawable_image,s.get_center(),2,(255,255,255),1)
            distance_from_center = s.get_distance_from_center()
            if distance_from_center is not None:
                cv2.putText(drawable_image, str(distance_from_center), s.get_center(), cv2.FONT_HERSHEY_SIMPLEX, 1.0, s.get_color_bgr(), lineType=cv2.LINE_AA)
            # cv2.putText(drawable_image, s.get_color_name(), s.get_center(), cv2.FONT_HERSHEY_SIMPLEX, 1.0, s.get_color_bgr(), lineType=cv2.LINE_AA)
        
        cv2.imshow("drawable_image window", drawable_image)
        cv2.waitKey(3)

        try:
            self.image_pub.publish(self.bridge.cv2_to_imgmsg(cv_image, "bgr8"))
        except CvBridgeError as e:
            print(e)

    def initialize_board(self):
        while not self.board.center_found():
            print("Press enter to search for the center")
            raw_input()
            # input()
            self.center_search()
            rospy.rostime.wallsleep(1)
            while self.center_search_flag:
                rospy.rostime.wallsleep(1)

        rospy.rostime.wallsleep(1)

        while not self.board.get_error and self.board.get_center is not None:
            print("Press enter to search for the center")
            raw_input()
            # input()
            self.center_search()
    
    def close(self):
        cv2.destroyAllWindows()

    def evaluate_board(self):
        print("Press enter to evaluate the board")
        raw_input()
        # input()
        self.stone_search()
        rospy.rostime.wallsleep(1)

def main(args):
    ic = image_converter()
    try:
        # rospy.spin()

        ic.initialize_board()
        # while not rospy.core.is_shutdown():
            # while not ic.board.center_found():
            #     print("Press enter to search for the center")
            #     raw_input()
            #     # input()
            #     ic.center_search()
            #     rospy.rostime.wallsleep(1)
            #     while ic.center_search_flag:
            #         rospy.rostime.wallsleep(1)

            # rospy.rostime.wallsleep(1)

            # while not ic.board.get_error and ic.board.get_center is not None:
            #     print("Press enter to search for the center")
            #     raw_input()
            #     # input()
            #     ic.center_search()

        while not rospy.core.is_shutdown():
            print("Press enter to search for stones")
            raw_input()
            # input()
            ic.stone_search()
            rospy.rostime.wallsleep(1)

    except KeyboardInterrupt:
        print("Shutting down")
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main(sys.argv)