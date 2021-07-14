#!/usr/bin/env python
import argparse
import numpy as np
import torch
import time
import pickle
from tensorboardX import SummaryWriter
import gym

from pathlib import Path
import csv

#import files...
from naf import NAF
from ounoise import OUNoise
from replay_memory import Transition, ReplayMemory
from cabinet_env import CabinetEnv


def main():
    parser = argparse.ArgumentParser(description='PyTorch X-job')
    parser.add_argument('--algo', default='NAF',
                        help='algorithm to use: NAF | DDPG')
    parser.add_argument('--env_name', default="CabinetEnv",
                        help='name of the environment')
    parser.add_argument('--gamma', type=float, default=0.99, metavar='G',
                        help='discount factor for reward (default: 0.99)')
    parser.add_argument('--tau', type=float, default=0.001,
                        help='discount factor for model (default: 0.001)')
    parser.add_argument('--ou_noise', type=bool, default=True)
    parser.add_argument('--constr_gauss_sample', type=bool, default=False,
                        help='Should we use constrained Gaussian sampling?')
    parser.add_argument('--noise_scale', type=float, default=0.5, metavar='G',
                        help='initial noise scale (default: 0.5)')
    parser.add_argument('--final_noise_scale', type=float, default=0.2, metavar='G',####0.2
                        help='final noise scale (default: 0.2)')
    parser.add_argument('--optimize_actions', type=bool, default=False,
                        help='add loss to objective')
    parser.add_argument('--exploration_end', type=int, default=100, metavar='N',
                        help='number of episodes with noise (default: 100)')
    parser.add_argument('--seed', type=int, default=54123, metavar='N',####4
                        help='random seed (default: 4)')
    parser.add_argument('--batch_size', type=int, default=1024, metavar='N',
                        help='batch size (default: 1024)')
    parser.add_argument('--num_steps', type=int, default=100, metavar='N',
                        help='max episode length (default: 100)')
    parser.add_argument('--num_episodes', type=int, default=500, metavar='N',
                        help='number of episodes (default: 500)')
    parser.add_argument('--hidden_size', type=int, default=128, metavar='N',
                        help='hidden size (default: 128)')
    parser.add_argument('--updates_per_step', type=int, default=10, metavar='N',###20
                    help='model updates per simulator step (default: 10)')
    parser.add_argument('--run_id', type=int, default=0, metavar='N',
                        help='increment this externally to re-run same parameters multiple times')
    parser.add_argument('--replay_size', type=int, default=1000000, metavar='N',
                        help='size of replay buffer (default: 1000000)')
    parser.add_argument('--save_agent', type=bool, default=True,
                        help='save model to file')
    parser.add_argument('--train_model', type=bool, default=True,
                        help='Training or run')
    parser.add_argument('--load_agent', type=bool, default=False,
                        help='load model from file')
    parser.add_argument('--load_exp', type=bool, default=False,
                        help='load saved experience')
    parser.add_argument('--logdir', default="/home/quantao/naf_logs",
                        help='directory where to dump log files')
    parser.add_argument('--action_scale', type=float, default=1.0, metavar='N',
                        help='scale applied to the normalized actions (default: 1.0)')
    parser.add_argument('--kd', type=float, default=0.0, metavar='N',
                        help='derivative gain for ee_rl (default: 0.0)')
    parser.add_argument('--greedy_steps', type=int, default=10, metavar='N',
                        help='amount of times greedy goes (default: 10)')

    args = parser.parse_args()

    print("++++++action_scale:{} optimize_actions:{}++++++".format(args.action_scale, args.optimize_actions))

    if args.env_name == 'CabinetEnv':
        env = CabinetEnv(bEffort=False)
        env.set_scale(args.action_scale)
        env.set_kd(args.kd)
    else:
        env = gym.make(args.env_name)
    
    #writer = SummaryWriter(args.logdir+'/runs/sd{}_us_{}'.format(args.seed,args.updates_per_step))
    basename = 'sd{}_us_{}_ns_{}_run_{}'.format(args.seed,args.updates_per_step,args.noise_scale,args.run_id)
    writer = SummaryWriter(args.logdir+'/runs/'+basename)

    path = Path(args.logdir)
    if not path.exists():
        raise argparse.ArgumentTypeError("Parameter {} is not a valid path".format(path))

    csv_train = open(args.logdir+'/'+basename+'_train.csv', 'w', newline='')
    train_writer = csv.writer(csv_train, delimiter=' ')

    csv_test = open(args.logdir+'/'+basename+'_test.csv', 'w', newline='')
    test_writer = csv.writer(csv_test, delimiter=' ')

    env.seed(args.seed)
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    # -- initialize agent --
    agent = NAF(args.gamma, args.tau, args.hidden_size,
                env.observation_space.shape[0], env.action_space)

    # -- declare memory buffer and random process N
    memory = ReplayMemory(args.replay_size)
    ounoise = OUNoise(env.action_space.shape[0]) if args.ou_noise else None

    # -- load existing model --
    if args.load_agent:
        agent.load_model(args.env_name, args.batch_size, args.num_episodes, basename+'.pth', model_path=args.logdir)
        print('loaded agent '+basename+' from '+args.logdir)

    # -- load experience buffer --
    if args.load_exp:
        with open(args.logdir+'/'+basename+'.pk', 'rb') as input:
            memory.memory = pickle.load(input)
            memory.position = len(memory)

    rewards = []
    updates = 0
    
    # env cleanup
    env.stop()
    
    t_start = time.time()
    for i_episode in range(args.num_episodes+1):
        # -- reset environment for every episode --
        print('++++++++++++++++++++++++++i_episode+++++++++++++++++++++++++++++:', i_episode)
        
        scale = (args.noise_scale - args.final_noise_scale) * max(0, args.exploration_end - i_episode) / args.exploration_end + args.final_noise_scale
        #scale = [min(scale,0.4), min(scale,0.2)]
        print("noise scale is {}".format(scale))

        # -- initialize noise (random process N) --
        if args.ou_noise:
            ounoise.scale = scale
            ounoise.reset()
    
        episode_numsteps = 0
        episode_reward = 0
        episode_reached = 0
        episode_violation = 0
        visits = []
        Ax_prev = np.identity(env.action_space.shape[0])
        bx_prev = env.action_space.high
        
        states_visited = []
        actions_taken = []
        
        t_project = 0
        t_act = 0
        
        t_st = time.time()
        #state = env.reset()
        state = torch.Tensor([env.start()])
        print("reset took {}".format(time.time() - t_st))
        
        Ax = np.identity(env.action_space.shape[0])
        bx = env.action_space.high
                    
        switch_once = 0
        while True:
            # -- action selection, observation and store transition --
            if args.ou_noise:               
                action, Q = agent.select_action(state, ounoise) if args.train_model else agent.select_action(state)
            else:
                if args.constr_gauss_sample:
                    #Gaussian noise sample
                    action, Q = agent.select_proj_action(state, Ax_prev, bx_prev, simple_noise=scale)
                else:
                    #noise-free run
                    action, Q = agent.select_proj_action(state, Ax_prev, bx_prev)
                    
            ''' env step '''
            t_st0 = time.time()            
            next_state, reward, done = env.step(action)
            t_act += time.time() - t_st0
            #print("act took {}".format(time.time() - t_st0))   
            
            '''switch constraint phase'''
            if env.constraint_phase == 2 and switch_once == 0:
                env.switch_constraint_phase()
                env.switch_phase_done = True
                switch_once = 1

            # only take error space(3-dimension) from state space
            Q = Q.detach()
            visits = np.concatenate((visits,state.numpy()[0][-3:],args.action_scale*action,[reward]),axis=None)
            #env.render()       
            episode_numsteps += 1
            episode_reward += reward

            action = torch.Tensor(action)
            mask = torch.Tensor([not done])
            reward = torch.Tensor([reward])
            next_state = torch.Tensor([next_state])
            Ax_trace = torch.Tensor(Ax)
            bx_trace = torch.Tensor([bx])
            
            # for plot_path
            states_visited.append(state)
            actions_taken.append(action)
            #print("reward:", reward)
            
            if reward > -5000:
                memory.push(state, action, mask, next_state, reward, Ax_trace, bx_trace)
                
            state = next_state
                
            if done or episode_numsteps == args.num_steps:
                if done:
                    print("To break due to reaching goal")                
                    episode_reached += 1
                else:
                    print("To break due to 200 steps per episode")
                    
                #episode_violation = env.constraint_violations                    
                break
            
        if env.bViolated:
            print("one violation")
            episode_violation += 1
            
        writer.add_scalar('reward/train', episode_reward, i_episode)    
        print("Train Episode: {}, episode numsteps: {}, reward: {}, time: {} act: {} project: {}".format(i_episode, episode_numsteps,
                                                                         episode_reward, time.time()-t_st, t_act, t_project))
        #print("Percentage of actions in constraint violation was {}".format(np.sum([env.episode_trace[i][2]>0 for i in range(len(env.episode_trace))])))

        train_writer.writerow(np.concatenate(([episode_reward],[episode_violation],[episode_reached],visits),axis=None))
        rewards.append(episode_reward)
        
        #trying out this?
        env.stop()
        t_st = time.time()
        
        #Training models
        if len(memory) > args.batch_size and args.train_model:
            print("Training model")

            t_st = time.time()
            for _ in range(args.updates_per_step):
                transitions = memory.sample(args.batch_size)
                batch = Transition(*zip(*transitions))
                value_loss, reg_loss = agent.update_parameters(batch, optimize_feasible_mu=args.optimize_actions)
                
                writer.add_scalar('loss/full', value_loss, updates)
                if args.optimize_actions:
                    writer.add_scalar('loss/value', value_loss-reg_loss, updates)
                    writer.add_scalar('loss/regularizer', reg_loss, updates)
                
                updates += 1
            print("train took {}".format(time.time() - t_st))
        #Training end
        
        #plot state value functions!!!!!!
        agent.plot_path(states_visited, actions_taken, i_episode)
            
        if time.time() - t_st < 4:
            print("waiting for reset...")
            time.sleep(5.0)
            print("DONE")
            
        '''--runing evaluation episode--'''
        if i_episode > 200 and i_episode % 2 == 0:
            #state = env.reset()
            print('+++++++++++++++++++++evaluation i_episode++++++++++++++++++++++++:', i_episode)
            state = torch.Tensor([env.start()])
            Ax_prev = np.identity(env.action_space.shape[0])
            bx_prev = env.action_space.high

            greedy_numsteps = 0
            episode_violation = 0
            episode_reward = 0
            visits = []
            switch_once = 0
            while True:
                action, Q = agent.select_action(state)
                
                next_state, reward, done = env.step(action)
                
                '''switch constraint phase'''
                if env.constraint_phase == 2 and switch_once == 0:
                    env.switch_constraint_phase()
                    env.switch_phase_done = True
                    switch_once = 1
                
                Q = Q.detach()
                visits = np.concatenate((visits, state.numpy()[0][-3:], args.action_scale*action, [reward]), axis=None)
                episode_reward += reward
                greedy_numsteps += 1
                
                #state = next_state
                state = torch.Tensor([next_state])

                if done or greedy_numsteps == args.num_steps:
                    print("evaluation break")
                    #episode_violation = env.constraint_violations
                    break
            
            writer.add_scalar('reward/test', episode_reward, i_episode)
            test_writer.writerow(np.concatenate(([episode_reward], [episode_violation], visits), axis=None))

            rewards.append(episode_reward)
            print("Evaluation Episode: {}, total numsteps: {}, reward: {}, average reward: {}".format(i_episode, episode_numsteps, rewards[-1], np.mean(rewards[-10:])))
            print('Time per episode: {} s'.format((time.time() - t_start) / (i_episode+1)))
            #print("Percentage of actions in constraint violation was {}".format(np.sum([env.episode_trace[i][2]>0 for i in range(len(env.episode_trace))])))

            env.stop()
            time.sleep(4.0) #wait for reset

    # -- close environment --
    env.close()

    #-- saves model --
    if args.save_agent:
        agent.save_model(args.env_name, args.batch_size, args.num_episodes, basename+'.pth')
        with open(args.logdir+'/'+basename+'.pk', 'wb') as output:
            pickle.dump(memory.memory, output, pickle.HIGHEST_PROTOCOL)

    print('Training ended after {} minutes'.format((time.time() - t_start)/60.0))
    print('Time per episode: {} s'.format((time.time() - t_start) / args.num_episodes))
    print('Mean reward: {}'.format(np.mean(rewards)))
    print('Max reward: {}'.format(np.max(rewards)))
    print('Min reward: {}'.format(np.min(rewards)))
    

if __name__ == '__main__':
    main()
