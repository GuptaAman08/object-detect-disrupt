import torch
import torchvision
import torchvision.transforms as transforms
import torchvision.utils as vutils
from torch.autograd import Variable
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.backends.cudnn as cudnn
from models.vgg import VGG
from models.lenet import LeNet
import models.resnet as resnet
import models.densenet as densenet
import models.alexnet as alexnet
import models.googlenet as googlenet
import attacks
import numpy as np
import pdb
import pandas as pd
import os
import data_loader
import utils

use_cuda = torch.cuda.is_available()
i = 0  # Epsilon counter for logging


def load_cifar():
    """
    Load and normalize the training and test data for CIFAR10
    """
    print('==> Preparing data..')
    transform_train = transforms.Compose([
        transforms.RandomCrop(32, padding=4),
        transforms.RandomHorizontalFlip(),
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])

    transform_test = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
    ])

    trainset = torchvision.datasets.CIFAR10(
        root='./data', train=True, download=True, transform=transform_train)
    trainloader = torch.utils.data.DataLoader(
        trainset, batch_size=1024, shuffle=True, num_workers=8)

    testset = torchvision.datasets.CIFAR10(
        root='./data', train=False, download=True, transform=transform_test)
    testloader = torch.utils.data.DataLoader(
        testset, batch_size=128, shuffle=False, num_workers=8)
    return trainloader, testloader


def load_lfw():

    file_ext = 'jpg'  # observe, no '.' before jpg

    dataset_path = './data/lfw'

    pairs_path = './data/pairs.txt'

    pairs = utils.read_pairs(pairs_path)
    path_list, issame_list = utils.get_paths(
        args.dataset_path, pairs, file_ext)

    print('==> Preparing data..')
    # Define data transforms
    RGB_MEAN = [0.485, 0.456, 0.406]
    RGB_STD = [0.229, 0.224, 0.225]
    test_transform = transforms.Compose([
        transforms.Scale((250, 250)),  # make 250x250
        transforms.CenterCrop(150),   # then take 150x150 center crop
        # resized to the network's required input size
        transforms.Scale((224, 224)),
        transforms.ToTensor(),
        transforms.Normalize(mean=RGB_MEAN,
                             std=RGB_STD),
    ])

    # Create data loader
    test_loader = torch.utils.data.DataLoader(
        data_loader.LFWDataset(
            path_list, issame_list, test_transform),
        batch_size=args.batch_size, shuffle=False)

    return test_loader


def train(model, optimizer, criterion, trainloader, architecture, attacker=None, num_epochs=25, freq=10, early_stopping=True):
    """
    Train the model with the optimizer and criterion for num_epochs epochs on data trainloader.
    attacker is an object that produces adversial inputs given regular inputs.
    Return the accuracy on the normal inputs and on the perturbed inputs.

    To save time, only perturb inputs on the last epoch, at the frequency freq.
    """
    for epoch in range(num_epochs):
        running_loss = 0.0
        total, correct, correct_adv, total_adv = 0.0, 0.0, 0.0, 1.0
        early_stop_param = 0.01
        for i, data in enumerate(trainloader):
            inputs, labels = data
            inputs = Variable(
                (inputs.cuda() if use_cuda else inputs), requires_grad=True)
            labels = Variable(
                (labels.cuda() if use_cuda else labels), requires_grad=False)

            y_hat = model(inputs)
            loss = criterion(y_hat, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            _, predicted = torch.max(y_hat.data, 1)
            total += labels.size(0)
            correct += predicted.eq(labels.data).sum()

            # print statistics
            running_loss = loss.data[0]

            if attacker:
                # only perturb inputs on the last epoch, to save time
                # if (i+1) % freq == 0: #  and (epoch == num_epochs - 1):
                adv_inputs, adv_labels, num_unperturbed = attacker.attack(
                    inputs, labels, model, optimizer)
                correct_adv += num_unperturbed
                total_adv += labels.size(0)

            if (i+1) % freq == 0:
                print('[%s: %d, %5d] loss: %.4f' % (architecture, epoch + 1, i + 1, running_loss / 2),
                      correct/total, correct_adv/total_adv)
                if early_stopping:
                    if running_loss < early_stop_param:
                        print("Early Stopping !!!!!!!!!!")
                        break
                running_loss = 0.0

    return correct/total, correct_adv/total_adv


def test(model, criterion, testloader, attacker, model_name, att_name):
    """
    Test the model with the data from testloader.
    attacker is an object that produces adversial inputs given regular inputs.
    Return the accuracy on the normal inputs and the unperturbed inputs.
    """
    epsilons = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    resultsDF = pd.DataFrame(
        columns=('Model', 'Attacker', 'Epsilon', 'Test_acc', 'Test_att_acc'))
    global i
    for epsilon in epsilons:
        correct, correct_adv, total = 0.0, 0.0, 0.0
        for data in testloader:
            inputs, labels = data
            inputs = Variable(
                (inputs.cuda() if use_cuda else inputs), requires_grad=True)
            labels = Variable(
                (labels.cuda() if use_cuda else labels), requires_grad=False)
            y_hat = model(inputs)
            loss = criterion(y_hat, labels)
            loss.backward()

            predicted = torch.max(y_hat.data, 1)[1]
            correct += predicted.eq(labels.data).sum()

            _, adv_labels, num_unperturbed = attacker.attack(
                inputs, labels, model, epsilon)
            adv_inputs = attacker.perturb(inputs, epsilon=epsilon)
            correct_adv += num_unperturbed

            total += labels.size(0)

        fake = adv_inputs
        samples_name = 'images/'+name+str(epsilon) + '_samples.png'
        vutils.save_image(fake.data, samples_name)
        print(('Test Acc Acc: %.4f | Test Attacked Acc; %.4f'
               % (100.*correct/total, 100.*correct_adv/total)))
        resultsDF.loc[i] = [model_name, att_name,
                            epsilon, correct/total, correct_adv/total]
        i = i + 1
    resultsDF.to_csv('DCGAN_attack_results.csv', mode='a',
                     header=(not os.path.exists('DCGAN_attack_results.csv')))
    pdb.set_trace()
    return correct/total, correct_adv/total


def prep(model):
    if model and use_cuda:
        model.cuda()
        model = torch.nn.DataParallel(
            model, device_ids=list(range(torch.cuda.device_count())))
        cudnn.benchmark = True
    return model


if __name__ == "__main__":
    trainloader, testloader = load_cifar()
    criterion = nn.CrossEntropyLoss()
    do_train = True
    architectures = [
        (VGG, 'VGG16', 50),
        (resnet.ResNet18, 'res18', 500),
        (densenet.densenet_cifar, 'dense121', 500),
        (alexnet.AlexNet, 'alex', 500),
        (googlenet.GoogLeNet, 'googlenet', 500),
        (LeNet, 'lenet', 250)
    ]

    for init_func, name, epochs in architectures:
        for tr_adv in [False, True]:
            print(name, tr_adv)
            model = prep(init_func())
            attacker = attacks.DCGAN(train_adv=tr_adv)

            optimizer = optim.Adam(model.parameters(), lr=1e-4)
            if do_train:
                train_acc, train_adv_acc = train(model, optimizer,
                                                 criterion, trainloader, name, attacker, num_epochs=epochs)
                suffix = '_AT' if tr_adv else ''
                attacker.save(
                    'saved/{0}{1}_nodrop_joey_attacker_0.0010.pth'.format(name, suffix))
                torch.save(model.state_dict(),
                           'saved/{0}{1}_no_drop_joey.pth'.format(name, suffix))
            else:
                attacker.load('saved/res18_nodrop_joey_attacker_0.0010.pth')
                model.load_state_dict(torch.load('saved/dense121_joey.pth'))
                tr_adv = False
                suffix = '_AT' if tr_adv else ''
                attacker_name = 'res18_no_drop' + suffix
                name = name + suffix
                test_acc, test_adv_acc = test(model, criterion, testloader,
                                              attacker, name, attacker_name)

            pdb.set_trace()
            suffix = '_AT' if tr_adv else ''
            attacker.save(
                'saved/{0}{1}_attacker_0.01.pth'.format(name, suffix))
            torch.save(model.state_dict(),
                       'saved/{0}{1}.pth'.format(name, suffix))

    """
	model = prep(VGG('VGG16'))
	model2 = prep(VGG('VGG16'))

	# use default hyperparams for best results!
	# attacker = attacks.FGSM()
	# attacker = attacks.CarliniWagner(verbose=True)
	attacker = attacks.DCGAN(train_adv=False)

	criterion = nn.CrossEntropyLoss()

	# train first model adversarially
	optimizer = optim.SGD(model.parameters(), lr=1e-3, momentum=0.9, weight_decay=5e-4)
	train_acc, train_adv_acc = train(model, optimizer, criterion, trainloader, attacker, num_epochs=50)
	test_acc, test_adv_acc = test(model, criterion, testloader, attacker)
	attacker.save('VGG_attack_0.005.pth')
	torch.save(model.state_dict(), 'VGG_50.pth')
	"""

    """
	# train second model normally
	# attacker.load('VGG_attack_0.005.pth')
	model2.load_state_dict(torch.load('VGG_50.pth'))

	optimizer2 = optim.SGD(model2.parameters(), lr=1e-3, momentum=0.9, weight_decay=5e-4)
	train_acc, train_adv_acc = train(model2, optimizer2, criterion, trainloader, num_epochs=50)
	torch.save(model2.state_dict(), 'resnet_50.pth')

	test_acc, test_adv_acc = test(model2, criterion, testloader, attacker)

	# print 'Train accuracy of the network on the 10000 test images:', train_acc, train_adv_acc
        print 'Test accuracy of the network on the 10000 test images:', test_acc, test_adv_acc
	"""
