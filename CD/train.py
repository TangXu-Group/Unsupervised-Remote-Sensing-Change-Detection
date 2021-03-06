import os
import sys
import torch
import torch.nn as nn
from torch.nn import init
import functools
from torch.optim import lr_scheduler
import numpy as np
import scipy.io as sio
import matplotlib.pyplot as plt
import h5py
import math
import matplotlib.gridspec as gridspec
import pickle as pickle
from networks import FeatureExtractor9FeatureFromLayer23
from networks import FeatureExtractor9FeatureFromLayer8
from networks import FeatureExtractor9FeatureFromLayer10
from networks import FeatureExtractor9FeatureFromLayer11
from networks import FeatureExtractor9FeatureFromLayer5
from networks import FeatureExtractor9FeatureFromLayer2
from skimage.transform import resize
from skimage import filters
from skimage import morphology
import cv2 as cv
from kmodes.kmodes import KModes
import PIL
import cv2
from scipy.spatial.distance import cdist
import scipy.stats as sistats
from options import options

##Parsing options
opt = options().parseOptions()
dataPath = opt.dataPath
inputChannels = opt.inputChannels
outputLayerNumbers = np.array(opt.layersToProcess.split(','),dtype=np.int)
thresholdingStrategy = opt.thresholding
otsuScalingFactor = opt.otsuScalingFactor
objectMinSize = opt.objectMinSize
topPercentSaturationOfImageOk=opt.topPercentSaturationOfImageOk
topPercentToSaturate=opt.topPercentToSaturate



nanVar=float('nan')

#Defining parameters related to the CNN
sizeReductionTable=[nanVar,nanVar,1,nanVar,nanVar,2,nanVar,nanVar,4,nanVar,\
                            4,4,4,4,4,4,4,4,4,
                            nanVar,2,nanVar,nanVar,1,nanVar,nanVar,1,1] 
featurePercentileToDiscardTable=[nanVar,nanVar,90,nanVar,nanVar,90,nanVar,nanVar,95,nanVar,\
                            95,95,95,95,95,95,95,95,95,nanVar,95,nanVar,nanVar,95
                            ,nanVar,nanVar,0,0]
filterNumberTable=[nanVar,nanVar,64,nanVar,nanVar,128,nanVar,nanVar,256,nanVar,\
                            256,256,256,256,256,256,256,256,256,nanVar,128,nanVar,nanVar,64,nanVar,nanVar,1,1]

#here "0", the starting index is reflectionPad2D which is not a real layer. So when 
#later operations like filterNumberForOutputLayer=filterNumberTable[outputLayerNumber] are taken, it works, as 0 is dummy and indexing starts from 1

#Reading Image
from skimage import io
from PIL import Image

def read_sentinel_img_4(path):
    """Read cropped Sentinel-2 image: RGB and NIR bands."""
    im_name = os.listdir(path)[0][:-7]
    r = io.imread(path + im_name + "B04.tif")
    g = io.imread(path + im_name + "B03.tif")
    b = io.imread(path + im_name + "B02.tif")
    nir = io.imread(path + im_name + "B08.tif")
    
    I = np.stack((r,g,b,nir),axis=2).astype('float')  
#     if NORMALISE_IMGS:
    I = (I - I.mean()) / I.std()
    return I

# OSCD
preChangeImage = read_sentinel_img_4(dataPath + 'imgs_1/')
postChangeImage = read_sentinel_img_4(dataPath + 'imgs_2/')

# QB and ZY3
# preChangeImage = np.array(Image.open(dataPath + 't1.bmp')).astype('float')
# postChangeImage = np.array(Image.open(dataPath + 't2.bmp')).astype('float')

# SZTAKI
# preChangeImage = np.array(Image.open(dataPath + 'im1.bmp'))
# postChangeImage = np.array(Image.open(dataPath + 'im2.bmp'))



print(preChangeImage.shape)
print(type(preChangeImage))

preChangeImageOriginalShape = preChangeImage.shape
if preChangeImageOriginalShape[0]<preChangeImageOriginalShape[1]: ##code is written in a way s.t. it expects row>col
    preChangeImage = np.swapaxes(preChangeImage,0,1)
    postChangeImage = np.swapaxes(postChangeImage,0,1)

    
class saturateImage():
##Defines code for image adjusting/pre-processing

    def __init__(self):
        """Reset the class; indicates the class hasn't been initailized"""
        self.initialized = False

    def saturateSomePercentileMultispectral(self,inputMap,percentileToSaturate):
        inputMap=inputMap.astype(float)
        inputMapNormalized=inputMap
        for iter in range(inputMap.shape[2]):
            inputMapBand=inputMap[:,:,iter]
            inputMapNormalizedBand=(inputMapBand-np.amin(inputMapBand))/(np.percentile(inputMapBand,(100-percentileToSaturate))-np.amin(inputMapBand))
            inputMapNormalizedBand[inputMapNormalizedBand>1]=1
            inputMapNormalized[:,:,iter]=inputMapNormalizedBand
        return inputMapNormalized
    
#Pre-change and post-change image normalization
if topPercentSaturationOfImageOk:
    preChangeImageNormalized=saturateImage().saturateSomePercentileMultispectral(preChangeImage, topPercentToSaturate)
    postChangeImageNormalized=saturateImage().saturateSomePercentileMultispectral(postChangeImage, topPercentToSaturate)
    


#Reassigning pre-change and post-change image to normalized values
data1=np.copy(preChangeImageNormalized)
data2=np.copy(postChangeImageNormalized)

#Checking image dimension
imageSize=data1.shape
imageSizeRow=imageSize[0]
imageSizeCol=imageSize[1]
imageNumberOfChannel=imageSize[2]


input_nc=imageNumberOfChannel #input number of channels
output_nc=6 #from Potsdam dataset number of classes
ngf=64 # number of gen filters in first conv layer
norm_layer = nn.BatchNorm2d
use_dropout=False



netForFeatureExtractionLayer23=FeatureExtractor9FeatureFromLayer23(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
netForFeatureExtractionLayer11=FeatureExtractor9FeatureFromLayer11(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
netForFeatureExtractionLayer10=FeatureExtractor9FeatureFromLayer10(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
netForFeatureExtractionLayer8=FeatureExtractor9FeatureFromLayer8(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
netForFeatureExtractionLayer5=FeatureExtractor9FeatureFromLayer5(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
netForFeatureExtractionLayer2=FeatureExtractor9FeatureFromLayer2(input_nc, output_nc, ngf, norm_layer, use_dropout, 9)
if inputChannels=='RGB':
    state_dict=torch.load('./trainedNet/RGB/trainedModelFinal')
    if imageNumberOfChannel!=3:
        sys.exit('Input images do not have 3 channels while loaded model is for R-G-B input')
elif inputChannels=='RGBNIR':
    state_dict=torch.load('./trainedNet/RGBIR/trainedModelFinal')
    if imageNumberOfChannel!=4:
        sys.exit('Input images do not have 4 channels while loaded model is for R-G-B-NIR input')
else:
    sys.exit('Image channels not valid - valid arguments RGB or RGBNIR')
state_dict=torch.load('./trainedNet/RGBIR/trainedModelFinal') 


netForFeatureExtractionLayer23Dict=netForFeatureExtractionLayer23.state_dict()
state_dictForLayer23=state_dict
state_dictForLayer23={k: v for k, v in netForFeatureExtractionLayer23Dict.items() if k in state_dictForLayer23}

netForFeatureExtractionLayer11Dict=netForFeatureExtractionLayer11.state_dict()
state_dictForLayer11=state_dict
state_dictForLayer11={k: v for k, v in netForFeatureExtractionLayer11Dict.items() if k in state_dictForLayer11}

netForFeatureExtractionLayer10Dict=netForFeatureExtractionLayer10.state_dict()
state_dictForLayer10=state_dict
state_dictForLayer10={k: v for k, v in netForFeatureExtractionLayer10Dict.items() if k in state_dictForLayer10}

netForFeatureExtractionLayer8Dict=netForFeatureExtractionLayer8.state_dict()
state_dictForLayer8=state_dict
state_dictForLayer8={k: v for k, v in netForFeatureExtractionLayer8Dict.items() if k in state_dictForLayer8}

netForFeatureExtractionLayer5Dict=netForFeatureExtractionLayer5.state_dict()
state_dictForLayer5=state_dict
state_dictForLayer5={k: v for k, v in netForFeatureExtractionLayer5Dict.items() if k in state_dictForLayer5}

netForFeatureExtractionLayer2Dict=netForFeatureExtractionLayer2.state_dict()
state_dictForLayer2=state_dict
state_dictForLayer2={k: v for k, v in netForFeatureExtractionLayer2Dict.items() if k in state_dictForLayer2}

netForFeatureExtractionLayer23.load_state_dict(state_dictForLayer23)
netForFeatureExtractionLayer11.load_state_dict(state_dictForLayer11)
netForFeatureExtractionLayer10.load_state_dict(state_dictForLayer10)
netForFeatureExtractionLayer8.load_state_dict(state_dictForLayer8)
netForFeatureExtractionLayer5.load_state_dict(state_dictForLayer5)
netForFeatureExtractionLayer2.load_state_dict(state_dictForLayer2)


input_nc=imageNumberOfChannel #input number of channels
output_nc=imageNumberOfChannel #output number of channels
ngf=64 # number of gen filters in first conv layer
norm_layer = functools.partial(nn.InstanceNorm2d, affine=False, track_running_stats=True)
use_dropout=False



##changing all nets to eval mode
netForFeatureExtractionLayer23.eval()
netForFeatureExtractionLayer23.requires_grad=False

netForFeatureExtractionLayer11.eval()
netForFeatureExtractionLayer11.requires_grad=False

netForFeatureExtractionLayer10.eval()
netForFeatureExtractionLayer10.requires_grad=False

netForFeatureExtractionLayer8.eval()
netForFeatureExtractionLayer8.requires_grad=False

netForFeatureExtractionLayer5.eval()
netForFeatureExtractionLayer5.requires_grad=False

netForFeatureExtractionLayer2.eval()
netForFeatureExtractionLayer2.requires_grad=False


torch.no_grad()


eachPatch=imageSizeRow
numImageSplitRow=imageSizeRow/eachPatch
numImageSplitCol=imageSizeCol/eachPatch
cutY=list(range(0,imageSizeRow,eachPatch))
cutX=list(range(0,imageSizeCol,eachPatch))
additionalPatchPixel=64


layerWiseFeatureExtractorFunction=[nanVar,nanVar,netForFeatureExtractionLayer2,nanVar,nanVar,netForFeatureExtractionLayer5,nanVar,nanVar,netForFeatureExtractionLayer8,nanVar,\
                            netForFeatureExtractionLayer10,netForFeatureExtractionLayer11,nanVar,nanVar,nanVar,nanVar,nanVar,nanVar,nanVar,nanVar,\
                            nanVar,nanVar,nanVar,netForFeatureExtractionLayer23,nanVar,nanVar,nanVar,nanVar]

 

##Checking validity of feature extraction layers
validFeatureExtractionLayers=[2,5,8,10,11,23] ##Feature extraction from only these layers have been defined here
for outputLayer in outputLayerNumbers:
    if outputLayer not in validFeatureExtractionLayers:
        sys.exit('Feature extraction layer is not valid, valid values are 2,5,8,10,11,23')
        
##Extracting bi-temporal features
modelInputMean=0.406

for outputLayerIter in range(0,len(outputLayerNumbers)):
        outputLayerNumber=outputLayerNumbers[outputLayerIter]
        filterNumberForOutputLayer=filterNumberTable[outputLayerNumber]
        featurePercentileToDiscard=featurePercentileToDiscardTable[outputLayerNumber]
        featureNumberToRetain=int(np.floor(filterNumberForOutputLayer*((100-featurePercentileToDiscard)/100)))
        sizeReductionForOutputLayer=sizeReductionTable[outputLayerNumber]
        patchOffsetFactor=int(additionalPatchPixel/sizeReductionForOutputLayer)
        print('Processing layer number:'+str(outputLayerNumber))
        
        timeVector1Feature=np.zeros([imageSizeRow,imageSizeCol,filterNumberForOutputLayer])
        timeVector2Feature=np.zeros([imageSizeRow,imageSizeCol,filterNumberForOutputLayer])
        
        
        if ((imageSizeRow<eachPatch) | (imageSizeCol<eachPatch)):
            if imageSizeRow>imageSizeCol:
                patchToProcessDate1=np.pad(data1,[(0,0),(0,imageSizeRow-imageSizeCol),(0,0)],'symmetric')
                patchToProcessDate2=np.pad(data2,[(0,0),(0,imageSizeRow-imageSizeCol),(0,0)],'symmetric')
            if imageSizeCol>imageSizeRow:
                patchToProcessDate1=np.pad(data1,[(0,imageSizeCol-imageSizeRow),(0,0),(0,0)],'symmetric')
                patchToProcessDate2=np.pad(data2,[(0,imageSizeCol-imageSizeRow),(0,0),(0,0)],'symmetric')
            if imageSizeRow==imageSizeCol:
                patchToProcessDate1=data1
                patchToProcessDate2=data2
                
            patchToProcessDate1=patchToProcessDate1-modelInputMean
            inputToNetDate1=torch.from_numpy(patchToProcessDate1)
            inputToNetDate1=inputToNetDate1.float()
            inputToNetDate1=np.swapaxes(inputToNetDate1,0,2)
            inputToNetDate1=np.swapaxes(inputToNetDate1,1,2)
            inputToNetDate1=inputToNetDate1.unsqueeze(0)
            del patchToProcessDate1
                        
            patchToProcessDate2=patchToProcessDate2-modelInputMean
            inputToNetDate2=torch.from_numpy(patchToProcessDate2)
            inputToNetDate2=inputToNetDate2.float()
            inputToNetDate2=np.swapaxes(inputToNetDate2,0,2)
            inputToNetDate2=np.swapaxes(inputToNetDate2,1,2)
            inputToNetDate2=inputToNetDate2.unsqueeze(0)
            del patchToProcessDate2
            
            #running model on image 1 and converting features to numpy format
            with torch.no_grad():
                obtainedFeatureVals1=layerWiseFeatureExtractorFunction[outputLayerNumber](inputToNetDate1)
            obtainedFeatureVals1=obtainedFeatureVals1.squeeze()
            obtainedFeatureVals1=obtainedFeatureVals1.data.numpy()
            del inputToNetDate1
            
            #running model on image 2 and converting features to numpy format
            with torch.no_grad():
                obtainedFeatureVals2=layerWiseFeatureExtractorFunction[outputLayerNumber](inputToNetDate2)
            obtainedFeatureVals2=obtainedFeatureVals2.squeeze()
            obtainedFeatureVals2=obtainedFeatureVals2.data.numpy()
            del inputToNetDate2
            
            for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[0:imageSizeRow,\
                                           0:imageSizeCol,processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       0:int(imageSizeRow/sizeReductionForOutputLayer),\
                                                                       0:int(imageSizeCol/sizeReductionForOutputLayer)],\
                                                                       (imageSizeRow,imageSizeCol))
            for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[0:imageSizeRow,\
                                           0:imageSizeCol,processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       0:int(imageSizeRow/sizeReductionForOutputLayer),\
                                                                       0:int(imageSizeCol/sizeReductionForOutputLayer)],\
                                                                       (imageSizeRow,imageSizeCol))
       
            
            
                
        
        if not((imageSizeRow<eachPatch) | (imageSizeCol<eachPatch)):
            for kY in range(0,len(cutY)):
                for kX in range(0,len(cutX)):
                    
                    #extracting subset of image 1
                    if (kY==0 and kX==0):
                        patchToProcessDate1=data1[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kY==0 and kX!=(len(cutX)-1)):
                        patchToProcessDate1=data1[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       (cutX[kX]-additionalPatchPixel):(cutX[kX]+eachPatch),:]
                    elif (kY!=(len(cutY)-1) and kX==(len(cutX)-1)):
                        patchToProcessDate1=data1[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       (imageSizeCol-eachPatch-additionalPatchPixel):(imageSizeCol),:] 
                    elif (kX==0 and kY!=(len(cutY)-1)):
                        patchToProcessDate1=data1[(cutY[kY]-additionalPatchPixel):\
                                                  (cutY[kY]+eachPatch),\
                                                       cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kX!=(len(cutX)-1) and kY==(len(cutY)-1)):
                        patchToProcessDate1=data1[(imageSizeRow-eachPatch-additionalPatchPixel):\
                                                  (imageSizeRow),\
                                                       cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kY==(len(cutY)-1) and kX==(len(cutX)-1)):
                        patchToProcessDate1=data1[(imageSizeRow-eachPatch-additionalPatchPixel):\
                                                  (imageSizeRow),\
                                                       (imageSizeCol-eachPatch-additionalPatchPixel):(imageSizeCol),:]
                    else:
                        patchToProcessDate1=data1[(cutY[kY]-additionalPatchPixel):\
                                                  (cutY[kY]+eachPatch),\
                                                  (cutX[kX]-additionalPatchPixel):(cutX[kX]+eachPatch),:]
                    #extracting subset of image 2   
                    if (kY==0 and kX==0):
                        patchToProcessDate2=data2[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kY==0 and kX!=(len(cutX)-1)):
                        patchToProcessDate2=data2[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       (cutX[kX]-additionalPatchPixel):(cutX[kX]+eachPatch),:]
                    elif (kY!=(len(cutY)-1) and kX==(len(cutX)-1)):
                        patchToProcessDate2=data2[cutY[kY]:(cutY[kY]+eachPatch+additionalPatchPixel),\
                                                       (imageSizeCol-eachPatch-additionalPatchPixel):(imageSizeCol),:] 
                    elif (kX==0 and kY!=(len(cutY)-1)):
                        patchToProcessDate2=data2[(cutY[kY]-additionalPatchPixel):\
                                                  (cutY[kY]+eachPatch),\
                                                      cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kX!=(len(cutX)-1) and kY==(len(cutY)-1)):
                        patchToProcessDate2=data2[(imageSizeRow-eachPatch-additionalPatchPixel):\
                                                  (imageSizeRow),\
                                                       cutX[kX]:(cutX[kX]+eachPatch+additionalPatchPixel),:]
                    elif (kY==(len(cutY)-1) and kX==(len(cutX)-1)):
                        patchToProcessDate2=data2[(imageSizeRow-eachPatch-additionalPatchPixel):\
                                                  (imageSizeRow),\
                                                       (imageSizeCol-eachPatch-additionalPatchPixel):(imageSizeCol),:]    
                    else:
                        patchToProcessDate2=data2[(cutY[kY]-additionalPatchPixel):\
                                                  (cutY[kY]+eachPatch),\
                                                  (cutX[kX]-additionalPatchPixel):(cutX[kX]+eachPatch),:]
                    print(kY)
                    print(kX)
                    print(patchToProcessDate1.shape)
                    print(patchToProcessDate2.shape)
                                    
                    #converting to pytorch varibales and changing dimension for input to net
                    patchToProcessDate1=patchToProcessDate1-modelInputMean
                    
                    inputToNetDate1=torch.from_numpy(patchToProcessDate1)
                    del patchToProcessDate1
                    inputToNetDate1=inputToNetDate1.float()
                    inputToNetDate1=np.swapaxes(inputToNetDate1,0,2)
                    inputToNetDate1=np.swapaxes(inputToNetDate1,1,2)
                    inputToNetDate1=inputToNetDate1.unsqueeze(0)
                    
                    
                    patchToProcessDate2=patchToProcessDate2-modelInputMean
                    
                    inputToNetDate2=torch.from_numpy(patchToProcessDate2)
                    del patchToProcessDate2
                    inputToNetDate2=inputToNetDate2.float()
                    inputToNetDate2=np.swapaxes(inputToNetDate2,0,2)
                    inputToNetDate2=np.swapaxes(inputToNetDate2,1,2)
                    inputToNetDate2=inputToNetDate2.unsqueeze(0)
                    
                    
                    #running model on image 1 and converting features to numpy format
                    with torch.no_grad():
                        obtainedFeatureVals1=layerWiseFeatureExtractorFunction[outputLayerNumber](inputToNetDate1)
                    obtainedFeatureVals1=obtainedFeatureVals1.squeeze()
                    obtainedFeatureVals1=obtainedFeatureVals1.data.numpy()
                    del inputToNetDate1
                    
                    #running model on image 2 and converting features to numpy format
                    with torch.no_grad():
                        obtainedFeatureVals2=layerWiseFeatureExtractorFunction[outputLayerNumber](inputToNetDate2)
                    obtainedFeatureVals2=obtainedFeatureVals2.squeeze()
                    obtainedFeatureVals2=obtainedFeatureVals2.data.numpy()
                    del inputToNetDate2
                    
                    
                    obtainedFeatureVals1=np.clip(obtainedFeatureVals1,-1,+1)
                    obtainedFeatureVals2=np.clip(obtainedFeatureVals2,-1,+1)
                    
                                    
                    if (kY==0 and kX==0):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       (eachPatch,eachPatch))
                        
                    elif (kY==0 and kX!=(len(cutX)-1)):                                                    
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1)],\
                                                                       (eachPatch,eachPatch))
                    elif (kY!=(len(cutY)-1) and kX==(len(cutX)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):                        
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:imageSizeCol,processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       (obtainedFeatureVals1.shape[2]-1-int((imageSizeCol-cutX[kX])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals1.shape[2])],\
                                                                       (eachPatch,(imageSizeCol-cutX[kX])))
                    elif (kX==0 and kY!=(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       (eachPatch,eachPatch))
                    elif (kX!=(len(cutX)-1) and kY==(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:imageSizeRow,\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       (obtainedFeatureVals1.shape[1]-1-int((imageSizeRow-cutY[kY])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals1.shape[1]),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       ((imageSizeRow-cutY[kY]),eachPatch))
                    elif (kX==(len(cutX)-1) and kY==(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       (obtainedFeatureVals1.shape[1]-1-int((imageSizeRow-cutY[kY])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals1.shape[1]),\
                                                                       (obtainedFeatureVals1.shape[2]-1-int((imageSizeCol-cutX[kX])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals1.shape[2])],\
                                                                       ((imageSizeRow-cutY[kY]),(imageSizeCol-cutX[kX])))
                    else:
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector1Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals1[processingFeatureIter,\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1),\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1)],\
                                                                       (eachPatch,eachPatch))
                    #obtaining features from image 2: resizing and truncating additionalPatchPixel
                    if (kY==0 and kX==0):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       (eachPatch,eachPatch))
                        
                    elif (kY==0 and kX!=(len(cutX)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1)],\
                                                                       (eachPatch,eachPatch))
                    elif (kY!=(len(cutY)-1) and kX==(len(cutX)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:imageSizeCol,processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer),\
                                                                       (obtainedFeatureVals2.shape[2]-1-int((imageSizeCol-cutX[kX])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals2.shape[2])],\
                                                                       (eachPatch,(imageSizeCol-cutX[kX])))
                    elif (kX==0 and kY!=(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       (eachPatch,eachPatch))
                    elif (kX!=(len(cutX)-1) and kY==(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:imageSizeRow,\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       (obtainedFeatureVals2.shape[1]-1-int((imageSizeRow-cutY[kY])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals2.shape[1]),\
                                                                       0:int(eachPatch/sizeReductionForOutputLayer)],\
                                                                       ((imageSizeRow-cutY[kY]),eachPatch))
                    elif (kX==(len(cutX)-1) and kY==(len(cutY)-1)):
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       (obtainedFeatureVals2.shape[1]-1-int((imageSizeRow-cutY[kY])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals2.shape[1]),\
                                                                       (obtainedFeatureVals2.shape[2]-1-int((imageSizeCol-cutX[kX])/sizeReductionForOutputLayer)):\
                                                                       (obtainedFeatureVals2.shape[2])],\
                                                                       ((imageSizeRow-cutY[kY]),(imageSizeCol-cutX[kX])))
                    else:
                        for processingFeatureIter in range(0,filterNumberForOutputLayer):
                            timeVector2Feature[cutY[kY]:(cutY[kY]+eachPatch),\
                                           cutX[kX]:(cutX[kX]+eachPatch),processingFeatureIter]=\
                                           resize(obtainedFeatureVals2[processingFeatureIter,\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1),\
                                                                       (patchOffsetFactor+1):\
                                                                       (int(eachPatch/sizeReductionForOutputLayer)+patchOffsetFactor+1)],\
                                                                       (eachPatch,eachPatch))
                                       
        del  obtainedFeatureVals1,obtainedFeatureVals2                             
        timeVectorDifferenceMatrix=timeVector1Feature-timeVector2Feature
        print(timeVectorDifferenceMatrix.shape)
        
        nonZeroVector=[]
        stepSizeForStdCalculation=int(imageSizeRow/2)
        for featureSelectionIter1 in range(0,imageSizeRow,stepSizeForStdCalculation):
            for featureSelectionIter2 in range(0,imageSizeCol,stepSizeForStdCalculation):
                timeVectorDifferenceSelectedRegion=timeVectorDifferenceMatrix\
                                                   [featureSelectionIter1:(featureSelectionIter1+stepSizeForStdCalculation),\
                                                    featureSelectionIter2:(featureSelectionIter2+stepSizeForStdCalculation),
                                                    0:filterNumberForOutputLayer]
                stdVectorDifferenceSelectedRegion=np.std(timeVectorDifferenceSelectedRegion,axis=(0,1))
                featuresOrderedPerStd=np.argsort(-stdVectorDifferenceSelectedRegion)   #negated array to get argsort result in descending order
                nonZeroVectorSelectedRegion=featuresOrderedPerStd[0:featureNumberToRetain]
                nonZeroVector=np.union1d(nonZeroVector,nonZeroVectorSelectedRegion)
            
       
                
        modifiedTimeVector1=timeVector1Feature[:,:,nonZeroVector.astype(int)]
        modifiedTimeVector2=timeVector2Feature[:,:,nonZeroVector.astype(int)]
        del timeVector1Feature,timeVector2Feature
        
        ##Normalize the features (separate for both images)
        meanVectorsTime1Image=np.mean(modifiedTimeVector1,axis=(0,1))      
        stdVectorsTime1Image=np.std(modifiedTimeVector1,axis=(0,1))
        normalizedModifiedTimeVector1=(modifiedTimeVector1-meanVectorsTime1Image)/stdVectorsTime1Image
        
        meanVectorsTime2Image=np.mean(modifiedTimeVector2,axis=(0,1))      
        stdVectorsTime2Image=np.std(modifiedTimeVector2,axis=(0,1))
        normalizedModifiedTimeVector2=(modifiedTimeVector2-meanVectorsTime2Image)/stdVectorsTime2Image
        
        ##feature aggregation across channels
        if outputLayerIter==0:
            timeVector1FeatureAggregated=np.copy(normalizedModifiedTimeVector1)
            timeVector2FeatureAggregated=np.copy(normalizedModifiedTimeVector2)
        else:
            timeVector1FeatureAggregated=np.concatenate((timeVector1FeatureAggregated,normalizedModifiedTimeVector1),axis=2)
            timeVector2FeatureAggregated=np.concatenate((timeVector2FeatureAggregated,normalizedModifiedTimeVector2),axis=2)
    
 
    
    
del netForFeatureExtractionLayer5, netForFeatureExtractionLayer8, netForFeatureExtractionLayer10, netForFeatureExtractionLayer11,netForFeatureExtractionLayer23   
    
absoluteModifiedTimeVectorDifference=np.absolute(saturateImage().saturateSomePercentileMultispectral(timeVector1FeatureAggregated,5)-\
saturateImage().saturateSomePercentileMultispectral(timeVector2FeatureAggregated,5)) 


detectedChangeMap=np.linalg.norm(absoluteModifiedTimeVectorDifference,axis=(2))
detectedChangeMapNormalized=(detectedChangeMap-np.amin(detectedChangeMap))/(np.amax(detectedChangeMap)-np.amin(detectedChangeMap))
#plt.figure()
#plt.imshow(detectedChangeMapNormalized)


cdMap=np.zeros(detectedChangeMapNormalized.shape, dtype=bool)
if thresholdingStrategy == 'adaptive':
    for sigma in range(101,202,50):
        adaptiveThreshold=2*filters.gaussian(detectedChangeMapNormalized,sigma)
        cdMapTemp=(detectedChangeMapNormalized>adaptiveThreshold) 
        cdMapTemp=morphology.remove_small_objects(cdMapTemp,min_size=objectMinSize)
        cdMap=cdMap | cdMapTemp
elif thresholdingStrategy == 'otsu':
    otsuThreshold=filters.threshold_otsu(detectedChangeMapNormalized)
    cdMap = (detectedChangeMapNormalized>otsuThreshold) 
    cdMap=morphology.remove_small_objects(cdMap,min_size=objectMinSize)
elif thresholdingStrategy == 'scaledOtsu':
    otsuThreshold=filters.threshold_otsu(detectedChangeMapNormalized)
    cdMap = (detectedChangeMapNormalized>otsuScalingFactor*otsuThreshold) 
    cdMap=morphology.remove_small_objects(cdMap,min_size=objectMinSize)
else: 
    sys.exit('Unknown thresholding strategy')
cdMap=morphology.binary_closing(cdMap,morphology.disk(3))

if preChangeImageOriginalShape[0]<preChangeImageOriginalShape[1]: ##Conformity to row>col
    cdMap = np.swapaxes(cdMap,0,1)

##Creating directory to save result
resultDirectory = './result/'
if not os.path.exists(resultDirectory):
    os.makedirs(resultDirectory)

#Saving the result
sio.savemat(resultDirectory+'binaryCdResult.mat', mdict={'cdMap': cdMap})
plt.imsave(resultDirectory+'binaryCdResult.png',np.repeat(np.expand_dims(cdMap,2),3,2).astype(float))

