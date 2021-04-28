#!/bin/bash
source /home/quantao/Workspaces/catkin_ws/devel/setup.bash
echo $ROS_PACKAGE_PATH
for seed in 123; do # 123 231 312; do
  for u_step in 10; do
    for noise in 2.0; do
      for runid in 0; do
#        /home/quantao/anaconda3/envs/py37/bin/python main.py --env PandaEnv --seed ${seed} --num_episodes 50 --run_id ${runid} --noise_scale ${noise} --logdir \
#/home/quantao/naf_logs/action_project/ --updates_per_step ${u_step} --exploration_end 45 --project_actions=True
#       /home/quantao/anaconda3/envs/py37/bin/python main.py --env PandaEnv --seed ${seed} --num_episodes 50  --run_id ${runid} --noise_scale ${noise} --logdir \
#/home/quantao/naf_logs/action_n_objective/ --updates_per_step ${u_step} --exploration_end 45 --project_actions=True --optimize_actions=True
        /home/quantao/anaconda3/envs/py37/bin/python main.py --env_name PandaEnv --seed ${seed} --num_episodes 50  --run_id ${runid} --noise_scale ${noise} --logdir \
/home/quantao/naf_logs/baseline/ --updates_per_step ${u_step} --exploration_end 45
      done
    done
  done
done
