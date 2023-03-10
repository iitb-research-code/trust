from .strategy import Strategy

import submodlib
import torch
from torch.autograd import Variable
from geomloss import SamplesLoss
from torch.utils.data import DataLoader, Dataset

class WASSAL_Hybrid(Strategy):
    
    """
    
    
    Parameters
    ----------
    labeled_dataset: torch.utils.data.Dataset
        The labeled dataset to be used in this strategy. For the purposes of selection, the labeled dataset is not used, 
        but it is provided to fit the common framework of the Strategy superclass.
    unlabeled_dataset: torch.utils.data.Dataset
        The unlabeled dataset to be used in this strategy. It is used in the selection process as described above.
        Importantly, the unlabeled dataset must return only a data Tensor; if indexing the unlabeled dataset returns a tuple of 
        more than one component, unexpected behavior will most likely occur.
    nclasses: int
        The number of classes being predicted by the neural network.
    args: dict
        A dictionary containing many configurable settings for this strategy. Each key-value pair is described below:
            
            - **batch_size**: The batch size used internally for torch.utils.data.DataLoader objects. (int, optional)
            - **device**: The device to be used for computation. PyTorch constructs are transferred to this device. Usually is one of 'cuda' or 'cpu'. (string, optional)
            - **loss**: The loss function to be used in computations. (typing.Callable[[torch.Tensor, torch.Tensor], torch.Tensor], optional)
            - **optimizer**: The optimizer to use for submodular maximization. Can be one of 'NaiveGreedy', 'StochasticGreedy', 'LazyGreedy' and 'LazierThanLazyGreedy'. (string, optional)
            - **eta**: A magnification constant that is used in all but gcmi. It is used as a value of query-relevance vs diversity trade-off. Increasing eta tends to increase query-relevance while reducing query-coverage and diversity. (float)
            - **embedding_type**: The type of embedding to compute for similarity kernel computation. This can be either 'gradients' or 'features'. (string)
            - **verbose**: Gives a more verbose output when calling select() when True. (bool)
    """
    
    def __init__(self, labeled_dataset, unlabeled_dataset, query_dataset,net, nclasses, args={}): #
        
        super(WASSAL_Hybrid, self).__init__(labeled_dataset, unlabeled_dataset, net, nclasses, args)        
        self.query_dataset = query_dataset

    def _proj_simplex(self,v):
        """
        v: PyTorch Tensor to be projected to a simplex

        Returns:
        w: PyTorch Tensor simplex projection of v
        """
        z = 1
        orig_shape = v.shape
        v = v.view(1, -1)
        shape = v.shape
        with torch.no_grad():
            mu = torch.sort(v, dim=1)[0]
            mu = torch.flip(mu, dims=(1,))
            cum_sum = torch.cumsum(mu, dim=1)
            j = torch.unsqueeze(torch.arange(1, shape[1] + 1, dtype=mu.dtype, device=mu.device), 0)
            rho = torch.sum(mu * j - cum_sum + z > 0.0, dim=1, keepdim=True) - 1.
            rho = rho.to(int)
            max_nn = cum_sum[torch.arange(shape[0]), rho[:, 0]]
            theta = (torch.unsqueeze(max_nn, -1) - z) / (rho.type(max_nn.dtype) + 1)
            w = torch.clamp(v - theta, min=0.0).view(orig_shape)
            return w


    def select(self, budget):
        """
        Selects next set of points. Weights are all reset since in this 
        strategy the datapoints are removed
        
        Parameters
        ----------
        budget: int
            Number of data points to select for labeling
            
        Returns
        ----------
        idxs: list
            List of selected data point indices with respect to unlabeled_dataset
        """	
        
        unlabeled_dataset_len=len(self.unlabeled_dataset)
        if(self.args['verbose']):
            print('There are',unlabeled_dataset_len,'Unlabeled dataset')
        
        #uniform distribution of weights
        simplex_target = Variable(torch.ones(unlabeled_dataset_len, requires_grad=True, device=self.device)/unlabeled_dataset_len)
        simplex_refrain = Variable(torch.ones(unlabeled_dataset_len, requires_grad=True, device=self.device)/unlabeled_dataset_len)
        query_dataset_len = len(self.query_dataset)
        private_dataset_len = len(self.private_dataset)
        beta = torch.ones(query_dataset_len)/query_dataset_len
        gamma = torch.ones(private_dataset_len)/private_dataset_len

        loss_func = SamplesLoss("sinkhorn", p=2, blur=0.05, scaling=0.8)

        unlabeled_dataloader = DataLoader(dataset=self.unlabeled_dataset, batch_size=unlabeled_dataset_len, shuffle=False)
        target_dataloader = DataLoader(dataset=self.query_dataset, batch_size=query_dataset_len, shuffle=False)
        refrain_dataloader = DataLoader(dataset=self.private_dataset, batch_size=private_dataset_len, shuffle=False)

        unlabeled_iter = iter(unlabeled_dataloader)
        target_iter=iter(target_dataloader)
        refrain_iter = iter(refrain_dataloader)

        unlabeled_imgs = next(unlabeled_iter)
        unlabeled_imgs = unlabeled_imgs[:,0,:,:]
        target_imgs, _ = next(target_iter)
        target_imgs = target_imgs[:,0,:,:]
        refrain_imgs, _ = next(refrain_iter)
        refrain_imgs = refrain_imgs[:,0,:,:]

        unlabeled_imgs = unlabeled_imgs.to(self.device)
        unlabeled_imgs.requires_grad = True
        target_imgs=target_imgs.to(self.device)
        refrain_imgs = refrain_imgs.to(self.device)
        beta = beta.to(self.device)
        gamma = gamma.to(self.device)
        
        optimizer = torch.optim.Adam([simplex_target, simplex_refrain], lr=self.args['wd_lr'])
        simplex_target.requires_grad = True
        for i in range(self.args['wd_num_epochs']):
            optimizer.zero_grad()
            loss_1 = loss_func(simplex_target, unlabeled_imgs.view(len(unlabeled_imgs), -1), beta, target_imgs.view(len(target_imgs), -1))
            loss_2 = loss_func(simplex_refrain, unlabeled_imgs.view(len(unlabeled_imgs), -1), gamma, refrain_imgs.view(len(refrain_imgs), -1))
            loss_3 = loss_func(simplex_target, unlabeled_imgs.view(len(unlabeled_imgs), -1), simplex_refrain, unlabeled_imgs.view(len(unlabeled_imgs), -1))
            loss = loss_1 + loss_2 - self.args['h']*loss_3
            loss.backward()
            optimizer.step()
            with torch.no_grad():
                simplex_target.copy_(Variable(self._proj_simplex(simplex_target.cpu().detach()).to(self.device)))
                simplex_refrain.copy_(Variable(self._proj_simplex(simplex_refrain.cpu().detach()).to(self.device)))
        
        print("loss:{}, loss_1:{}, loss_2:{}, loss_3:{}, h={}".format(loss.item(), loss_1.item(), loss_2.item(), loss_3.item(), self.args['h']))
        simplex_difference = abs(simplex_target-simplex_refrain)
        sorted_simplex_difference, indices = torch.sort(simplex_difference, descending=False)
        if(self.args['verbose']):
            print('length of unlabelled dataset',str(len(unlabeled_imgs)))
            # print('Totals Probability of the budget:',str(torch.sum(sorted_simplex[:budget])))
            print('selected indices len ',len(torch.Tensor.tolist(indices[:budget])))
        self.simplex_target = simplex_target
        self.simplex_refrain = simplex_refrain
        # self.update_simplexes(simplex_target, simplex_refrain)

        return torch.Tensor.tolist(indices[:budget])