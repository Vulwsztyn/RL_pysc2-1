'''
Actor and critic networks share conv. layers to process minimap & screen.
'''

from math import floor
import torch
import torch.nn as nn
from utils import arglist
from utils.layers import TimeDistributed, Flatten, Dense2Conv, init_weights


minimap_channels = 7
screen_channels = 17

# apply paddinga as 'same', padding = (kernel - 1)/2
conv_minimap = nn.Sequential(nn.Conv2d(minimap_channels, 16, 5, stride=1, padding=2),  # shape (N, 16, m, m)
                             nn.ReLU(),
                             nn.Conv2d(16, 32, 3, stride=1, padding=1),  # shape (N, 32, m, m)
                             nn.ReLU())

conv_screen = nn.Sequential(nn.Conv2d(screen_channels, 16, 5, stride=1, padding=2),  # shape (N, 16, m, m)
                            nn.ReLU(),
                            nn.Conv2d(16, 32, 3, stride=1, padding=1),  # shape (N, 32, m, m)
                            nn.ReLU())

dense_nonspatial = nn.Sequential(nn.Linear(arglist.NUM_ACTIONS, 32),
                                 nn.ReLU(),
                                 Dense2Conv())


class ActorNet(torch.nn.Module):
    def __init__(self):
        super(ActorNet, self).__init__()
        # spatial features
        self.minimap_conv_layers = conv_minimap
        self.screen_conv_layers = conv_screen

        # non-spatial features
        self.nonspatial_dense = dense_nonspatial

        # state representations
        self.layer_hidden = nn.Sequential(nn.Conv2d(32 * 3, 64, 3, stride=1, padding=1),
                                          nn.ReLU())
        # output layers
        self.layer_action = nn.Sequential(nn.Conv2d(64, 1, 1),
                                          nn.ReLU(),
                                          Flatten(),
                                          nn.Linear(arglist.FEAT2DSIZE * arglist.FEAT2DSIZE, arglist.NUM_ACTIONS))
        self.layer_screen1 = nn.Conv2d(64, 1, 1)
        self.layer_screen2 = nn.Conv2d(64, 1, 1)

        self.apply(init_weights)  # weight initialization
        self.train()  # train mode

    def forward(self, obs, valid_actions):
        obs_minimap = obs['minimap']
        obs_screen = obs['screen']
        obs_nonspatial = obs['nonspatial']
        
        # process observations
        m = self.minimap_conv_layers(obs_minimap)
        s = self.screen_conv_layers(obs_screen)
        n = self.nonspatial_dense(obs_nonspatial)

        state_h = torch.cat([m, s, n], dim=1)
        state_h = self.layer_hidden(state_h)
        pol_categorical = self.layer_action(state_h)
        pol_categorical = self._mask_unavailable_actions(pol_categorical, valid_actions)

        # conv. output
        pol_screen1 = self.layer_screen1_x(state_h)
        pol_screen2 = self.layer_screen2_x(state_h)
        return [pol_categorical, pol_screen1, pol_screen2]

    def _conv_output_shape(self, h_w, kernel_size=1, stride=1, pad=0, dilation=1):
        if type(kernel_size) is not tuple:
            kernel_size = (kernel_size, kernel_size)
        h = floor(((h_w[0] + (2 * pad) - (dilation * (kernel_size[0] - 1)) - 1) / stride) + 1)
        w = floor(((h_w[1] + (2 * pad) - (dilation * (kernel_size[1] - 1)) - 1) / stride) + 1)
        return h, w

    def _mask_unavailable_actions(self, policy, valid_actions):
        """
            Args:
                policy_vb, (1, num_actions)
                valid_action_vb, (num_actions)
            Returns:
                masked_policy_vb, (1, num_actions)
        """
        masked_policy_vb = policy * valid_actions
        masked_policy_vb /= masked_policy_vb.sum(1)
        return masked_policy_vb


class CriticNet(torch.nn.Module):
    def __init__(self):
        super(CriticNet, self).__init__()
        # process observation
        # spatial features
        # apply paddinga as 'same', padding = (kernel - 1)/2
        self.minimap_conv_layers = conv_minimap
        self.screen_conv_layers = conv_screen

        # non-spatial features
        self.nonspatial_dense = dense_nonspatial

        # process action
        # spatial action
        self.conv_action = nn.Sequential(nn.Conv2d(2, 16, 5, stride=1, padding=2),  # shape (N, 16, m, m)
                                         nn.ReLU(),
                                         nn.Conv2d(16, 32, 3, stride=1, padding=1),  # shape (N, 32, m, m)
                                         nn.ReLU())

        # non-spatial action
        self.action_dense = nn.Sequential(nn.Linear(arglist.NUM_ACTIONS, 32),
                                          nn.ReLU(),
                                          Dense2Conv())

        # state representations
        # screen + minimap + nonspatial_obs + spatial_act + nonspatial_act
        self.layer_hidden = nn.Sequential(nn.Conv2d(32 * 5, 64, 3, stride=1, padding=1),
                                          nn.ReLU(),
                                          nn.Conv2d(64, 1, 1),
                                          nn.ReLU(),
                                          Flatten())
        # output layers
        self.layer_value = nn.Linear(arglist.FEAT2DSIZE * arglist.FEAT2DSIZE, 1)
        self.apply(init_weights)  # weight initialization
        self.train()  # train mode

    def forward(self, obs, actions):
        obs_minimap = obs['minimap']
        obs_screen = obs['screen']
        obs_nonspatial = obs['nonspatial']

        act_categorical = actions['categorical']
        act_screen1 = actions['screen1']
        act_screen2 = actions['screen2']

        # process observations
        m = self.minimap_conv_layers(obs_minimap)
        s = self.screen_conv_layers(obs_screen)
        n = self.nonspatial_dense(obs_nonspatial)

        # process actions
        a_spatial = self.conv_action(torch.cat([act_screen1, act_screen2], dim=1))
        a_nonspatial = self.action_dense(act_categorical)

        # combine action & observation
        sa = torch.cat([m, s, n, a_spatial, a_nonspatial], dim=1)
        sa = self.layer_hidden(sa)
        q = self.layer_value(sa)
        return q

    def _conv_output_shape(self, h_w, kernel_size=1, stride=1, pad=0, dilation=1):
        if type(kernel_size) is not tuple:
            kernel_size = (kernel_size, kernel_size)
        h = floor(((h_w[0] + (2 * pad) - (dilation * (kernel_size[0] - 1)) - 1) / stride) + 1)
        w = floor(((h_w[1] + (2 * pad) - (dilation * (kernel_size[1] - 1)) - 1) / stride) + 1)
        return h, w
