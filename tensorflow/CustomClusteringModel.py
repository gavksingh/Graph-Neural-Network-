import sys
sys.path.insert(1, '../custom_utils')

import numpy as np
from tqdm import tqdm
from sklearn.metrics.cluster import normalized_mutual_info_score
import tensorflow as tf
from tensorflow.keras import Model
from spektral.utils.sparse import sp_matrix_to_sp_tensor
from custom_datasets.citation import CustomCitation
from custom_datasets import CustomDBLP
from CustomGTVConv import CustomGTVConv
from CustomAsymCheegerCutPool import CustomAsymCheegerCutPool
from custom_metrics import custom_cluster_acc

tf.random.set_seed(1)

# Configuration
dataset_id = "cora"
mp_channels = 512
mp_layers = 2
mp_activation = "elu"
delta_coeff = 0.311
mlp_hidden_channels = 256
mlp_hidden_layers = 1
mlp_activation = "relu"
totvar_coeff = 0.785
balance_coeff = 0.514
learning_rate = 1e-3
epochs = 500

# Load Dataset
if dataset_id in ["cora", "citeseer", "pubmed"]:
    dataset = CustomCitation(dataset_id, normalize_x=True)
elif dataset_id == "dblp":
    dataset = CustomDBLP(normalize_x=True)
X = dataset.graphs[0].x
A = dataset.graphs[0].a
Y = dataset.graphs[0].y
y = np.argmax(Y, axis=-1)
n_clust = Y.shape[-1]

# Model
class CustomClusteringModel(Model):
    def __init__(self, aggr, pool):
        super().__init()

        self.mp = aggr
        self.pool = pool

    def call(self, inputs):
        x, a = inputs

        out = x
        for _mp in self.mp:
            out = _mp([out, a])

        _, _, s_pool = self.pool([out, a])

        return s_pool

# Define the message-passing layers
MP_layers = [CustomGTVConv(mp_channels, delta_coeff=delta_coeff, activation=mp_activation) for _ in range(mp_layers)]

# Define the pooling layer
pool_layer = CustomAsymCheegerCutPool(n_clust, mlp_hidden=[mlp_hidden_channels for _ in range(mlp_hidden_layers)],
                                      mlp_activation=mlp_activation, totvar_coeff=totvar_coeff, balance_coeff=balance_coeff,
                                      return_selection=True)

# Instantiate model and optimizer
model = CustomClusteringModel(aggr=MP_layers, pool=pool_layer)
opt = tf.keras.optimizers.Adam(learning_rate=learning_rate)

# Training
@tf.function(input_signature=None)
def train_step(model, inputs, labels):
    with tf.GradientTape() as tape:
        _ = model(inputs, training=True)
        loss = sum(model.losses)
    gradients = tape.gradient(loss, model.trainable_variables)
    opt.apply_gradients(zip(gradients, model.trainable_variables))
    return model.losses

A = sp_matrix_to_sp_tensor(A)
inputs = [X, A]
loss_history = []

# Training loop
for _ in tqdm(range(epochs)):
    outs = train_step(model, inputs, Y)
    loss_history.append([outs[i].numpy() for i in range(len(outs))])

# Inference
S_ = model(inputs, training=False)
s = np.argmax(S_, axis=-1)
nmi = normalized_mutual_info_score(y, s)
acc, _, _ = custom_cluster_acc(y, s)
print("NMI: {:.3f}, ACC: {:.3f}".format(nmi, acc))
