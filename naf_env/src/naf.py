import os
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.autograd import Variable
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cmx
from mpl_toolkits.mplot3d import Axes3D
        
#@profile
def MSELoss(input, target):
    return torch.sum((input - target)**2) / input.data.nelement()

#@profile
def soft_update(target, source, tau):
    for target_param, param in zip(target.parameters(), source.parameters()):
        target_param.data.copy_(target_param.data * (1.0 - tau) + param.data * tau)

#@profile
def hard_update(target, source):
    for target_param, param in zip(target.parameters(), source.parameters()):
        target_param.data.copy_(param.data)

# -- Network --
class Policy(nn.Module):

    def __init__(self, hidden_size, num_inputs, action_space):
        super(Policy, self).__init__()
        self.action_space = action_space
        num_outputs = action_space.shape[0]

        self.bn0 = nn.BatchNorm1d(num_inputs)
        self.bn0.weight.data.fill_(1)
        self.bn0.bias.data.fill_(0)

        self.linear1 = nn.Linear(num_inputs, hidden_size)
        self.bn1 = nn.BatchNorm1d(hidden_size)
        self.bn1.weight.data.fill_(1)
        self.bn1.bias.data.fill_(0)

        self.linear2 = nn.Linear(hidden_size, hidden_size)
        self.bn2 = nn.BatchNorm1d(hidden_size)
        self.bn2.weight.data.fill_(1)
        self.bn2.bias.data.fill_(0)

        self.V = nn.Linear(hidden_size, 1)
        self.V.weight.data.mul_(0.1)
        self.V.bias.data.mul_(0.1)

        self.mu = nn.Linear(hidden_size, num_outputs)
        self.mu.weight.data.mul_(0.1)
        self.mu.bias.data.mul_(0.1)

        self.L = nn.Linear(hidden_size, num_outputs ** 2)
        self.L.weight.data.mul_(0.1)
        self.L.bias.data.mul_(0.1)

        self.tril_mask = Variable(torch.tril(torch.ones(
            num_outputs, num_outputs), diagonal=-1).unsqueeze(0))
        self.diag_mask = Variable(torch.diag(torch.diag(torch.ones(num_outputs, num_outputs))).unsqueeze(0))

    #@profile
    def forward(self, inputs):
        x, u = inputs
        x = self.bn0(x)
        x = (self.linear1(x)).tanh()
        x = (self.linear2(x)).tanh()

        V = self.V(x)
        mu = (self.mu(x)).tanh()

        Q = None
        if u is not None:
            num_outputs = mu.size(1)
            L = self.L(x).view(-1, num_outputs, num_outputs)
            L = L * \
                self.tril_mask.expand_as(
                    L) + torch.exp(L) * self.diag_mask.expand_as(L)
            P = torch.bmm(L, L.transpose(2, 1))

            u_mu = (u - mu).unsqueeze(2)
            A = -0.5 * \
                torch.bmm(torch.bmm(u_mu.transpose(2, 1), P), u_mu)[:, :, 0]

            Q = A + V

        return mu, Q, V


class NAF:

    def __init__(self, gamma, tau, hidden_size, num_inputs, action_space):
        self.action_space = action_space
        self.num_inputs = num_inputs

        self.model = Policy(hidden_size, num_inputs, action_space)
        self.target_model = Policy(hidden_size, num_inputs, action_space)
        self.optimizer = Adam(self.model.parameters(), lr=1e-3)

        self.gamma = gamma
        self.tau = tau

        hard_update(self.target_model, self.model)

    #@profile
    def select_action(self, state, action_noise=None):
        self.model.eval()
        mu, _, _ = self.model((Variable(state), None))
        self.model.train()
        mu = mu.data
        if action_noise is not None:
            mu += torch.Tensor(action_noise.noise())
        return mu.clamp(-1, 1)

    #@profile
    def update_parameters(self, batch):
        state_batch = Variable(torch.cat(batch.state))
        action_batch = Variable(torch.cat(batch.action))
        reward_batch = Variable(torch.cat(batch.reward))
        mask_batch = Variable(torch.cat(batch.mask))
        next_state_batch = Variable(torch.cat(batch.next_state))

        _, _, next_state_values = self.target_model((next_state_batch, None))

        reward_batch = reward_batch.unsqueeze(1)
        mask_batch = mask_batch.unsqueeze(1)

        expected_state_action_values = reward_batch + (self.gamma * mask_batch * next_state_values)

        _, state_action_values, _ = self.model((state_batch, action_batch))

        loss = MSELoss(state_action_values, expected_state_action_values)

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1)
        self.optimizer.step()

        soft_update(self.target_model, self.model, self.tau)

        return loss.item(), 0

    def save_model(self, env_name, batch_size, episode, suffix="", model_path=None):
        if not os.path.exists('models/'):
            os.makedirs('models/')

        if model_path is None:
            model_path = "models/naf_{}_{}_{}_{}".format(env_name, batch_size, episode, suffix)
        print('Saving model to {}'.format(model_path))
        torch.save(self.model.state_dict(), model_path)

    def load_model(self, env_name, batch_size, episode, suffix="", model_path=None):
        if model_path is None:
            model_path = "models/naf_{}_{}_{}_{}".format(env_name, batch_size, episode, suffix)
        print('Loading model from {}'.format(model_path))
        self.model.load_state_dict(torch.load(model_path))

    def plot_path(self, state, action, episode):
        self.model.eval()
        _, Q, _ = self.model((Variable(torch.cat(state)), Variable(torch.cat(action))))
        self.model.train()
        sx, sy, sz = torch.cat(state).numpy().T
        ax, ay, az = torch.cat(action).numpy().T

        qCat = []
        for j in range(len(Q.data.numpy())):
            qCat.append(Q.data.numpy()[j][0])
        
        # 3D plot
        fig = plt.figure()
        ax3d = fig.gca(projection='3d')
        ax3d.scatter3D(sx, sy, sz)
        ax3d.scatter3D(sx[-1], sy[-1], sz[-1], color='r')
        ax3d.set_xlabel('delta_x', fontsize=10, labelpad=20)
        ax3d.set_ylabel('delta_y', fontsize=10, labelpad=20)
        ax3d.set_zlabel('delta_z', fontsize=10, labelpad=20)
        #plt.xticks(np.arange(-0.3, 0.3, 0.1))
        #plt.yticks(np.arange(-0.3, 0.3, 0.1))
        plt.title("Trajectory")

        # plot arrow
        #ax3d.quiver(sx, sy, sz, ax/100.0, ay/100.0, az/100.0)
        cmap = plt.cm.viridis
        cNorm = colors.Normalize(vmin=np.min(qCat), vmax=np.max(qCat))
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=cmap)
        for i in range(len(sx)):
            colorVal = scalarMap.to_rgba(qCat[i])
            if i == len(sx)-1:
                colorVal = (1.0, 0.0, 0.0, 1.0)

            ax3d.quiver(sx[i], sy[i], sz[i], ax[i]/100.0, ay[i]/100.0, az[i]/100.0, fc=colorVal, ec=colorVal)
            
        fig = 'path_{}_{}'.format(episode, '.png')
        plt.savefig(fig, dpi=300)
        plt.close()

    def save_path(self, state, action, episode):
        sx, sy, sz = torch.cat(state).numpy().T
        ax, ay, az = torch.cat(action).numpy().T

        f=open('path.txt','a')
        for i in range(sx.size):
            f.write(str(sx[i])+' ')
            f.write(str(sy[i])+' ')
            f.write(str(sz[i])+' ')
            f.write(str(ax[i])+' ')
            f.write(str(ay[i])+' ')
            f.write(str(az[i])+' ')
        
            f.write('\n')
        
        f.write('\n')       
        f.close()

        
        
        
        
        
        
        
