import os
import torch
import torch.nn as nn
from torch.optim import Adam
from torch.autograd import Variable
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as colors
import matplotlib.cm as cmx
from mpl_toolkits.mplot3d import *
#import mpl_toolkits.mplot3d as a3
import quad

from faces import Faces
from scipy.spatial import HalfspaceIntersection
from scipy.spatial import ConvexHull
from scipy.optimize import linprog
      
  
#@profile
def MSELoss(input, target):
    return torch.sum((input - target)**2) / input.data.nelement()

def RegLoss(means,Ax_batch,bx_batch):
    #note this is not done in parallel. In general, the number of constraints can varry, so Ax and bx cannot be trivially stacked
    #suggestions for improvement welcome
    #computes 1/n sum \lambda^T(A_ix\mu - b_i) for \lmbda = ones*factor
    factor=10.0
    r = torch.nn.ReLU()
    #print("Ax_batch shape:", len(Ax_batch))
    return factor*torch.sum(torch.stack([torch.sum(r(torch.mm(Ax_batch[i], means[i, :].reshape([3, 1])) - bx_batch[i]))
                                  for i in range(len(Ax_batch))])) / len(Ax_batch)

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
        
        #regularizer for covariance matrix
        self.lam = 0.001

    #@profile
    def forward(self, inputs):
        x, u = inputs
        x = self.bn0(x)
        x = (self.linear1(x)).tanh()
        x = (self.linear2(x)).tanh()

        V = self.V(x)
        mu = (self.mu(x)).tanh()

        Q = None
        num_outputs = mu.size(1)
        L = self.L(x).view(-1, num_outputs, num_outputs)
        L = L * \
            self.tril_mask.expand_as(
                L) + torch.exp(L) * self.diag_mask.expand_as(L) + self.lam*self.diag_mask.expand_as(L)

        P = torch.bmm(L, L.transpose(2, 1))
        if u is not None:

            u_mu = (u - mu).unsqueeze(2)
            A = -0.5 * \
                torch.bmm(torch.bmm(u_mu.transpose(2, 1), P), u_mu)[:, :, 0]

            Q = A + V
        else:
            Q = V

        return mu, Q, V, P


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
        mu, Q, _, _ = self.model((Variable(state), None))
        self.model.train()
        mu = mu.data
        if action_noise is not None:
            mu += torch.Tensor(action_noise.noise())
        return mu.clamp(-1, 1), Q

    def select_proj_action(self, state, Ax, bx, action_noise=None, simple_noise=0):
        self.model.eval()
        mu, Q, V, P = self.model((Variable(state), None))
        self.model.train()
        mu = mu.data
        
        pa = quad.project_action_cov(mu.numpy()[0], Ax, bx, P.detach().numpy()[0])
        if action_noise is not None:
            pa = torch.Tensor([quad.project_action(pa + action_noise.noise(), Ax, bx)])
        else:
            if simple_noise!= 0:
                #use project with noise
                pa = torch.Tensor([quad.project_and_sample(pa, Ax, bx, simple_noise)])
            else:
                #no noise
                pa = torch.Tensor([pa])
                 
        return pa, Q
    
    def project_action(self, action, Ax, bx, P, action_noise=None, simple_noise=0):
        pa = quad.project_action_cov(action.numpy()[0], Ax, bx, P.detach().numpy()[0])
        if action_noise is not None:
            pa = torch.Tensor([quad.project_action(pa + action_noise.noise(), Ax, bx)])
        else:
            if simple_noise!= 0:
                #use project with noise
                pa = torch.Tensor([quad.project_and_sample(pa, Ax, bx, simple_noise)])
            else:
                #no noise
                pa = torch.Tensor([pa])
                 
        return pa
        
    #@profile
    def update_parameters(self, batch, optimize_feasible_mu=False):
        state_batch = Variable(torch.cat(batch.state))
        action_batch = Variable(torch.cat(batch.action))
        reward_batch = Variable(torch.cat(batch.reward))
        mask_batch = Variable(torch.cat(batch.mask))
        next_state_batch = Variable(torch.cat(batch.next_state))

        _, _, next_state_values, _ = self.target_model((next_state_batch, None))

        reward_batch = reward_batch.unsqueeze(1)
        mask_batch = mask_batch.unsqueeze(1)

        expected_state_action_values = reward_batch + (self.gamma * mask_batch * next_state_values)

        means, state_action_values, _, _ = self.model((state_batch, action_batch))

        loss = MSELoss(state_action_values, expected_state_action_values)
        if(optimize_feasible_mu):
            regularizer_loss = RegLoss(means, batch.Ax, batch.bx)
            loss = loss + regularizer_loss

        self.optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1)
        self.optimizer.step()

        soft_update(self.target_model, self.model, self.tau)

        if(optimize_feasible_mu):
            return loss.item(), regularizer_loss.item()
        else:
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

    # saves state value function as a pickle
    # @sample_range is a tripplet with per-dimension min,max,and n_samples
    def save_value_funct(self, base_name, episode, sample_range):
        n_dim = len(sample_range[0])
        axis_list = []
        for j in range(n_dim):
            di = torch.linspace(sample_range[0][j],sample_range[1][j],sample_range[2][j])
            axis_list.append(di)
        axis = tuple(axis_list)
        mesh = torch.meshgrid(axis)
        mesh = torch.stack(mesh,2)
        mesh = torch.flatten(mesh,start_dim=0,end_dim=1)
        #mesh = mesh.unsqueeze(0)

        self.model.eval()
        mu, _, V = self.model((Variable(mesh),None))
        self.model.train()

#        with open(base_name+"_ep{}_val.pk".format(episode), 'wb') as output:
#            pickle.dump((mu,V),output)

        #draw picture
        Varray = V.detach().numpy()
        #Varray = numpy.reshape(Varray,sample_range[2])
        Varray = np.reshape(Varray,-1)

        fig = plt.figure()
        cmap = plt.cm.viridis
        cNorm = colors.Normalize(vmin=np.min(Varray), vmax=np.max(Varray))
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=cmap)
        plt.plot(-0.2,-0.5,'ro')
        plt.plot([-0.8,0.8,0.8,-0.8,-0.8],[-0.8,-0.8,0.8,0.8,-0.8],'b-',linewidth=2)
        grid = mesh.numpy()
        plt.scatter(grid[:,0],grid[:,1],c=Varray)
        plt.title("Value function at episode {}".format(episode))
        plt.colorbar()
        plt.tight_layout()
        plt.xlim((sample_range[0][0], sample_range[1][0]))
        plt.ylim((sample_range[0][1], sample_range[1][1]))
        figname= base_name+"_ep{}_val.png".format(episode)
        plt.savefig(figname)
        plt.close()
        

    def plot_path(self, state, action, episode):
        self.model.eval()
        #print("state:", state)
        _, Q, _, _ = self.model((Variable(torch.cat(state),0), Variable(torch.cat(action),0)))
        self.model.train()
        sx, sy, sz = torch.cat(state).numpy().T[-3:]
        ax, ay, az = torch.cat(action).numpy().T

        qCat = []
        for j in range(len(Q.data.numpy())):
            qCat.append(Q.data.numpy()[j][0])
                    
        # 3D plot
        fig = plt.figure()
        ax3d = fig.gca(projection='3d')
        bar = ax3d.scatter3D(sx, sy, sz)
        ax3d.scatter3D(sx[0], sy[0], sz[0], color='red', marker='^')
        ax3d.scatter3D(sx[-1], sy[-1], sz[-1], color='green', marker='*')
        ax3d.set_xlabel('delta_x', fontsize=10, labelpad=20)
        ax3d.set_ylabel('delta_y', fontsize=10, labelpad=20)
        ax3d.set_zlabel('delta_z', fontsize=10, labelpad=20)
        ax3d.set_xlim(-0.5,0.5)
        ax3d.set_ylim(-0.5,0.5)
        ax3d.set_zlim(0,0.8)
        #plt.xticks(np.arange(-0.3, 0.3, 0.1))
        #plt.yticks(np.arange(-0.3, 0.3, 0.1))
        plt.title("Trajectory episode {}".format(episode))

        # plot arrow
        #ax3d.quiver(sx, sy, sz, ax/100.0, ay/100.0, az/100.0)
        cmap = plt.cm.viridis
        cNorm = colors.Normalize(vmin=np.min(qCat), vmax=np.max(qCat))
        scalarMap = cmx.ScalarMappable(norm=cNorm, cmap=cmap)
        for i in range(len(sx)):
            colorVal = scalarMap.to_rgba(qCat[i])
            #if i == len(sx)-1:
            #    colorVal = (0.0, 0.0, 1.0, 1.0)

            ax3d.quiver(sx[i], sy[i], sz[i], ax[i]/10.0, ay[i]/10.0, az[i]/10.0, fc=colorVal, ec=colorVal)
        
        fig.colorbar(bar,shrink=0.5)
        #plt.show()
        fig = 'path_{}_{}'.format(episode, '.png')
        plt.savefig(fig, dpi=300)
        plt.close()
        
    def plot_state_action_pair(self, state, action, action_naf, Ax, bx, episode, step):
        self.model.eval()
        _, Q, _, _ = self.model((Variable(torch.cat(state),0), Variable(torch.cat(action),0)))
        self.model.train()
        sx, sy, sz = torch.cat(state).numpy().T[-3:]
        ax, ay, az = torch.cat(action).numpy().T
        ax_naf, ay_naf, az_naf = torch.cat(action_naf).numpy().T

        qCat = []
        for j in range(len(Q.data.numpy())):
            qCat.append(Q.data.numpy()[j][0])
                    
        # plot state
        fig = plt.figure()
        ax3d = fig.gca(projection='3d')
        bar = ax3d.scatter3D(sx, sy, sz)
        #ax3d.scatter3D(sx[0], sy[0], sz[0], color='red', marker='^')
        ax3d.set_xlabel('error_x', fontsize=10, labelpad=20)
        ax3d.set_ylabel('error_y', fontsize=10, labelpad=20)
        ax3d.set_zlabel('error_z', fontsize=10, labelpad=20)
        ax3d.set_xlim(-0.5,0.5)
        ax3d.set_ylim(-0.5,0.5)
        ax3d.set_zlim(0,0.8)
        plt.title("Trajectory episode {} step {}".format(episode, step))

        
        # plot projected action
        ax3d.quiver(sx[0], sy[0], sz[0], ax[0]/10.0, ay[0]/10.0, az[0]/10.0, color='blue')
        
        # plot naf action
        ax3d.quiver(sx[0], sy[0], sz[0], ax_naf[0]/10.0, ay_naf[0]/10.0, az_naf[0]/10.0, color='red')        
        fig.colorbar(bar,shrink=0.5)
        
        # plot feasible action space
        #construct an LP to find a feasible point in upper space
        num_constraints = bx.shape[1]
        norm_vector = np.reshape(np.linalg.norm(Ax, axis=1), (num_constraints, 1))
        c = np.zeros((3+1,))
        c[-1] = -1
        A_up = np.hstack((Ax, norm_vector))
        # a feasible point that is furthest from constraints solution
        upper_feasible = linprog(c, A_ub=A_up, b_ub=bx, bounds=(None, None))
        if upper_feasible.success:
            feasible_point = upper_feasible.x[:-1]
        else:
            return
            
        halfspaces = np.hstack((Ax,np.reshape(-bx,(num_constraints,1))))
        #feasible_point = np.array([0.3, 0.3, 0.3])
        hs = HalfspaceIntersection(halfspaces, feasible_point)
        verts = hs.intersections
        verts = np.array([verts[:,0]+sx[0], verts[:,1]+sy[0], verts[:,2]+sz[0]]).T
        hull = ConvexHull(verts)
        simplices = hull.simplices
        #print("verts=", verts)
        org_triangles = [verts[s] for s in simplices]
        f = Faces(org_triangles)
        g = f.simplify()
        #print("g=", g)
        facecolors = list(map("C{}".format, range(len(g))))       
        pc = art3d.Poly3DCollection(g, facecolor='w', edgecolor="k", alpha=0.2)
        ax3d.add_collection3d(pc)       
        ax3d.quiver(0, 0, 0, 1, 0, 0, arrow_length_ratio=0.1, color='r')
        ax3d.quiver(0, 0, 0, 0, 1, 0, arrow_length_ratio=0.1, color='g')
        ax3d.quiver(0, 0, 0, 0, 0, 1, arrow_length_ratio=0.1, color='b')
        
        # show and save
        #plt.show()
        fig = 'path{}_{}.png'.format(episode, step)
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

    