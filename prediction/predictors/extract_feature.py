# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.
import numpy as np
from sklearn.metrics import mean_squared_error
import shutil,json
def get_accuracy(y_pred,y_true,threshold=0.01):
    a=(y_true-y_pred)/y_true 
    c=abs(y_true-y_pred)
    b=(np.where(abs(a)<=threshold ) )
    return len(b[0])/len(y_true)
   


def lat_metrics(y_pred,y_true):
    rmspe = (np.sqrt(np.mean(np.square((y_true - y_pred) / y_true)))) * 100
    rmse=np.sqrt(mean_squared_error(y_pred,y_true))    
    acc5=get_accuracy(y_pred,y_true,threshold=0.05)
    acc10=get_accuracy(y_pred,y_true,threshold=0.10)
    acc15=get_accuracy(y_pred,y_true,threshold=0.15)  
    return rmse,rmspe,rmse/np.mean(y_true),acc5,acc10,acc15

def get_flop(input_channel,output_channel,k,H,W,stride):
    paras=output_channel*(k*k*input_channel+1)
    flops=2*H/stride*W/stride*paras
    return flops,paras
def get_conv_mem(input_channel,output_channel,k,H,W,stride):
    paras=output_channel*(k*k*input_channel+1)
    mem=paras+output_channel*H/stride*W/stride+input_channel*H*W
    return mem

def get_depthwise_flop(input_channel,output_channel,k,H,W,stride):
    paras=output_channel*(k*k+1)
    flops=2*H/stride*W/stride*paras
    return flops, paras
def get_flops_params(blocktype,hw,cin,cout,kernelsize,stride):   
    if 'dwconv' in blocktype:
        return get_depthwise_flop(cin,cout,kernelsize,hw,hw,stride)
    elif 'conv' in blocktype:
        return get_flop(cin,cout,kernelsize,hw,hw,stride)
    elif 'fc' in blocktype:
        flop=(2*cin+1)*cout
        return flop,flop
def get_predict_features(config):
          
    mdicts={}
    layer=0
    for item in config:
        print(item)
    for item in config:
        op=item['op']
        if 'conv' in op or 'maxpool' in op or 'avgpool' in op:
            cout=item['cout']
            cin=item['cin']
            ks=item['ks'][1]
            s=item['strides'][1]
            inputh=item['inputh']           
                
        if op in ['channelshuffle','split']:
            [b,inputh,inputw,cin]=item['input_tensors'][0]

        if  'conv' in op:
            flops,params=get_flops_params(op,inputh,cin,cout,ks,s)        
            features=[inputh,cin,cout,ks,s,flops/2e6,params/1e6]
          
        elif 'fc' in op or 'fc-relu' in op:
                cout=item['cout']
                cin=item['cin']
                flop=(2*cin+1)*cout
                features=[cin,cout,flop/2e6,flop/1e6]
                
        elif 'pool' in op and 'global' not in op:
                features=[inputh,cin,cout,ks,s]
        elif 'global-pool' in op or 'global-avgpool' in op or  'gap' in op:
                inputh=1
                cin=item['cin']
                features=[inputh,cin]
        elif 'channelshuffle' in op:
                features=[inputh,cin]
        elif 'split' in op:
                features=[inputh,cin]
        elif 'se' in op or 'SE' in op:
                inputh=item['input_tensors'][-1][-2]
                cin=item['input_tensors'][-1][-1]
                features=[inputh,cin]
        elif 'concat' in op:  ## maximum 4 branches                   
                itensors=item['input_tensors']
                inputh=itensors[0][1]
                features=[inputh,len(itensors)]
                for it in itensors:
                    co=it[-1]
                    features.append(co)
                if len(features)<6:
                    features=features+[0]*(6-len(features))
                elif len(features)>6:
                    nf=features[0:6]
                    features=nf
                    features[1]=6
        elif op in ['hswish']:
                if 'inputh' in item:
                    inputh=item['inputh']
                else:
                    inputh=item['input_tensors'][0][1]
                cin=item['cin']
                features=[inputh,cin]
        elif op in ['bn','relu','bn-relu']:
                itensors=item['input_tensors']
                if len(itensors[0])==4:
                    inputh=itensors[0][1]
                    cin=itensors[0][3]
                else:
                    inputh=itensors[0][0]
                    cin=itensors[0][1]
                features=[inputh,cin]                   


        elif op in ['add-relu','add']:
                itensors=item['input_tensors']
                inputh=itensors[0][1]
                cin1=itensors[0][3]
                cin2=itensors[1][3]
                features=[inputh,cin1,cin2]
        mdicts[layer]={}
        mdicts[layer][op]=features
        layer+=1
    return mdicts
def read_model_latency(latency_file):
    
    f=open(latency_file,'r')
    dicts={}
    while True:
        line=f.readline()
        if not line:
            break
        content=line.strip().split(',')   
        model=content[1]      
        latency=float(content[2])
        dicts[model]=latency 
    return dicts

def read_kernel_latency(filename):
    f=open(filename,'r')
    X=[]
    Y=[]
    stds=[]
    erros=[]
    while True:
        line=f.readline()
        if not line:
            break 
        content=line.split(',')
        if len(content)>1 and content[-2]!="":
            op=content[1]
            features=[int(x) for x in content[2].split('_')]
            k=1
            if len(features)==5 and 'concat' not in op:
                (hw,cin,cout,k,s)=features
            elif len(features)==7:
                (hw,cin,cout,k,s,k1,s1)=features
                flops,params=get_flops_params('conv-bn-relu',hw,cin,cout,k,s)
                mem=get_conv_mem(cin,cout,k,hw,hw,s)
                features.append(flops/2e6)
                features.append(params/1e6)
                features.append(mem/1e6)
           
            elif len(features)==2 and 'global' not in op and 'hswish' not in op and 'bnrelu' not in op and 'relu' not in op and 'bn' not in op:
                (cin,cout)=features
                hw=1
                k=1
                s=1
            elif len(features)==2 and ('global' in op or 'hswish' in op):
                (hw,cin)=features
                k=1
            elif len(features)==2 and op in ['bnrelu','bn','relu']:
                (cin,hw)=features 
                features=[hw,cin]
                k=1
            elif len(features)==3 and op=='addrelu':
                (hw,cin1,cin2)=features

            elif len(features)==3 and ('shuffle' in op  or 'split' in op ):
                (cin,hw,group)=features
                features1=[hw,cin]
                features=features1
            elif len(features)==3 and 'se' in op:
                (hw,cin,group)=features
                features1=[hw,cin]
                features=features1
            elif 'concat' in op:
                hw=features[0]
                n=len(features[1:])
                features1=[hw,n]+features[1:]
                if n<4:
                    features1+=[0]*(4-n)
                features=list(features1)
            else:
                (hw,cin,k,s)=features
                cout=cin
                features1=[hw,cin,cout,k,s]
                features=features1
                
            if k<9:
                latency=float(content[3])
                if latency>0  :##movidius: <1000
                    try:
                        std=float(content[4])
                        e=std/latency*100
                    except:
                        std=0
                        e=0
                    if 'pool' not in op and 'global' not in op and 'shuffle' not in op and 'split' not in op and 'se' not in op and 'hswish' not in op and 'concat' not in op and op not in ['bnrelu','addrelu','bn','relu']:
                        flops,params=get_flops_params(op,hw,cin,cout,k,s)
                        features.append(flops/2e6)
                        features.append(params/1e6)
                        name='_'.join([str(hw),str(cin),str(cout),str(k),str(s)])+'.tflite'
                    
        
                    stds.append(std)
                    erros.append(std/latency*100)
                    writeline='_'.join(str(x) for x in features)+','+str(latency)+','+str(std)+','+str(std/latency*100)
                    if features not in X:
                        flag1=True
                        if op in 'concat':
                            for fe in features:
                                if fe>900:
                                    flag1=False
                        if flag1:
                            X.append(features)
                            Y.append(latency)
    return X,Y

def get_feature(op,inputh,cin,cout,ks,s):
    if s!=None and 'conv' in op:
               
                flops,params=get_flops_params(op,inputh,cin,cout,ks,s)
                features=[inputh,cin,cout,ks,s,flops/2e6,params/1e6]
               
    elif 'fc' in op:
                flop=(2*cin+1)*cout
                features=[cin,cout,flop/2e6,flop/1e6]

    elif 'pool' in op:
                features=[inputh,cin,cout,ks,s]
    elif 'se' in op:
        features=[inputh,cin]
    elif op in ['hwish','hswish']:
        features=[inputh,cin]
    
    return features

