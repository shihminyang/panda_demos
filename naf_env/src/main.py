#!/usr/bin/env python
import argparse
import matplotlib.pyplot as plt
import numpy as np
import torch
import time
import pickle
import matplotlib.colors as colors
import matplotlib.cm as cmx
import gym
from torch.autograd import Variable
from tensorboardX import SummaryWriter

#import files...
from naf import NAF
from ounoise import OUNoise
from replay_memory import Transition, ReplayMemory
from environment import ManipulateEnv



def main():
    parser = argparse.ArgumentParser(description='PyTorch X-job')
    parser.add_argument('--env_name', default="Pendulum-v0",
                        help='name of the environment')
    parser.add_argument('--gamma', type=float, default=0.99, metavar='G',
                        help='discount factor for reward (default: 0.99)')
    parser.add_argument('--tau', type=float, default=0.001,
                        help='discount factor for model (default: 0.001)')
    parser.add_argument('--ou_noise', type=bool, default=True)
    parser.add_argument('--noise_scale', type=float, default=0.4, metavar='G',
                        help='initial noise scale (default: 0.3)')
    parser.add_argument('--final_noise_scale', type=float, default=0.3, metavar='G',
                        help='final noise scale (default: 0.4)')
    parser.add_argument('--exploration_end', type=int, default=33, metavar='N',
                        help='number of episodes with noise (default: 100)')
    parser.add_argument('--seed', type=int, default=4, metavar='N',
                        help='random seed (default: 4)')
    parser.add_argument('--batch_size', type=int, default=200, metavar='N',
                        help='batch size (default: 512)')
    parser.add_argument('--num_steps', type=int, default=100, metavar='N',
                        help='max episode length (default: 300)')
    parser.add_argument('--num_episodes', type=int, default=5000, metavar='N',
                        help='number of episodes (default: 5000)')
    parser.add_argument('--hidden_size', type=int, default=128, metavar='N',
                        help='hidden size (default: 128)')
    parser.add_argument('--updates_per_step', type=int, default=5, metavar='N',
                    help='model updates per simulator step (default: 50)')
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
    parser.add_argument('--greedy_steps', type=int, default=10, metavar='N',
                        help='amount of times greedy goes (default: 10)')

    args = parser.parse_args()

    env = ManipulateEnv()
    #env = gym.make(args.env_name)
    writer = SummaryWriter('runs/')

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
        agent.load_model(args.env_name, args.batch_size, args.num_episodes, '.pth')
        print("agent: naf_{}_{}_{}_{}, is loaded".format(args.env_name, args.batch_size, args.num_episodes, '.pth'))

    # -- load experience buffer --
    if args.load_exp:
        with open('/home/quantao/Workspaces/catkin_ws/src/panda_demos/naf_env/src/exp_replay.pk1', 'rb') as input:
            memory.memory = pickle.load(input)
            memory.position = len(memory)

    rewards = []
    total_numsteps = 0
    updates = 0
    
    #env.init_ros()
    #env.reset()

    t_start = time.time()

    for i_episode in range(args.num_episodes+1):
        # -- reset environment for every episode --
        #state = env.reset()
        state = torch.Tensor([env.reset()])

        # -- initialize noise (random process N) --
        if args.ou_noise:
            ounoise.scale = (args.noise_scale - args.final_noise_scale) * max(
                0, args.exploration_end - i_episode / args.exploration_end + args.final_noise_scale)
            ounoise.reset()

        episode_reward = 0
        while True:
            # -- action selection, observation and store transition --
            action = agent.select_action(state, ounoise) if args.train_model else agent.select_action(state)
            
            next_state, reward, done, info = env.step(action)

            #env.render()
            total_numsteps += 1
            episode_reward += reward

            action = torch.Tensor(action)
            mask = torch.Tensor([not done])
            reward = torch.Tensor([reward])
            next_state = torch.Tensor([next_state])

            #print('reward:', reward)
            memory.push(state, action, mask, next_state, reward)

            state = next_state

            #else:
            #    time.sleep(0.005)

            #env.render()
            #time.sleep(0.005)
            #env.rate.sleep()

            if done or total_numsteps % args.num_steps == 0:
                break

        if len(memory) >= args.batch_size and args.train_model:
            env.reset()
            print("Training model")

            for _ in range(args.updates_per_step*args.num_steps):
                transitions = memory.sample(args.batch_size)
                batch = Transition(*zip(*transitions))
                value_loss, policy_loss = agent.update_parameters(batch)

                writer.add_scalar('loss/value', value_loss, updates)
                writer.add_scalar('loss/policy', policy_loss, updates)

                updates += 1
        writer.add_scalar('reward/train', episode_reward, i_episode)
        print("Train Episode: {}, total numsteps: {}, reward: {}".format(i_episode, total_numsteps,
                                                                                       episode_reward))

        rewards.append(episode_reward)
    
    
        greedy_numsteps = 0
        if i_episode % 10 == 0:
            #state = env.reset()
            state = torch.Tensor([env.reset()])

            episode_reward = 0
            while True:
                action = agent.select_action(state)
        
                next_state, reward, done, info = env.step(action)
                episode_reward += reward
                greedy_numsteps += 1
                        
                #state = next_state
                state = torch.Tensor([next_state])

                #env.render()
                #time.sleep(0.01)
                #   env.rate.sleep()

                if done or greedy_numsteps % args.num_steps == 0:
                    break
                
            writer.add_scalar('reward/test', episode_reward, i_episode)
        
            rewards.append(episode_reward)
            print("Episode: {}, total numsteps: {}, reward: {}, average reward: {}".format(i_episode, total_numsteps, rewards[-1], np.mean(rewards[-10:])))
            

    #-- saves model --
    if args.save_agent:
        agent.save_model(args.env_name, args.batch_size, args.num_episodes, '.pth')
        with open('exp_replay.pk1', 'wb') as output:
            pickle.dump(memory.memory, output, pickle.HIGHEST_PROTOCOL)

    print('Training ended after {} minutes'.format((time.time() - t_start)/60))
    print('Time per episode: {} s'.format((time.time() - t_start) / args.num_episodes))
    print('Mean reward: {}'.format(np.mean(rewards)))
    print('Max reward: {}'.format(np.max(rewards)))
    print('Min reward: {}'.format(np.min(rewards)))
    

if __name__ == '__main__':
    main()

