#ifndef TRAJECTORY_HANDLER_H
#define TRAJECTORY_HANDLER_H

#include "ros/ros.h"

#include "panda_insertion/Panda.hpp"
#include <boost/thread/mutex.hpp>

#include "vector"
#include "string"

typedef struct Point
{
    double x, y, z;
} Point;

typedef std::vector<Point> Trajectory;

class TrajectoryHandler
{
private:
    ros::NodeHandle* nodeHandler;
    Panda* panda;
    boost::mutex mutex;

public:
    TrajectoryHandler();
    TrajectoryHandler(ros::NodeHandle* nodeHandler, Panda* panda);

    Trajectory generateArchimedeanSpiral(double a, double b, int nrOfPoints);
    Trajectory generateInitialPositionTrajectory(int nrOfPoints);
    Trajectory generateExternalDownTrajectory(int nrOfPoints);
    Trajectory generateInternalUpTrajectory(int nrOfPoints);

    void writeTrajectoryToFile(Trajectory trajectory,
                               const std::string& fileName,
                               bool appendToFile = false);
};

#endif
