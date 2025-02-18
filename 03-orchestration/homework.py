import pandas as pd
from pyrsistent import b

from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error

import mlflow

from prefect import flow, task 
from prefect.task_runners import SequentialTaskRunner
from prefect import get_run_logger
from prefect.deployments import DeploymentSpec
from prefect.orion.schemas.schedules import CronSchedule
from prefect.flow_runners import SubprocessFlowRunner

import datetime
from datetime import date
from dateutil.relativedelta import *

import glob

import pickle

@task
def read_data(path):
    df = pd.read_parquet(path)
    return df

@task
def prepare_features(df, categorical, train=True):
    df['duration'] = df.dropOff_datetime - df.pickup_datetime
    df['duration'] = df.duration.dt.total_seconds() / 60
    df = df[(df.duration >= 1) & (df.duration <= 60)].copy()

    logger = get_run_logger()

    mean_duration = df.duration.mean()
    if train:
        logger.info(f"The mean duration of training is {mean_duration}")
        print(f"The mean duration of training is {mean_duration}")
    else:
        logger.info(f"The mean duration of validation is {mean_duration}")
        print(f"The mean duration of validation is {mean_duration}")
    
    df[categorical] = df[categorical].fillna(-1).astype('int').astype('str')
    return df

@task
def train_model(df, categorical):

    train_dicts = df[categorical].to_dict(orient='records')
    dv = DictVectorizer()
    X_train = dv.fit_transform(train_dicts) 
    y_train = df.duration.values

    logger = get_run_logger()

    shape_X_train = X_train.shape
    logger.info(f"The shape of X_train is {X_train.shape}")
    print(f"The shape of X_train is {X_train.shape}")

    len_dv_features = len(dv.feature_names_)
    logger.info(f"The DictVectorizer has {len(dv.feature_names_)} features")
    print(f"The DictVectorizer has {len(dv.feature_names_)} features")

    lr = LinearRegression()
    lr.fit(X_train, y_train)
    y_pred = lr.predict(X_train)
    mse = mean_squared_error(y_train, y_pred, squared=False)
    logger.info(f"The MSE of training is: {mse}")
    print(f"The MSE of training is: {mse}")
    return lr, dv

@task
def run_model(df, categorical, dv, lr):
    val_dicts = df[categorical].to_dict(orient='records')
    X_val = dv.transform(val_dicts) 
    y_pred = lr.predict(X_val)
    y_val = df.duration.values

    logger = get_run_logger()
    mse = mean_squared_error(y_val, y_pred, squared=False)
    logger.info(f"The MSE of validation is: {mse}")
    print(f"The MSE of validation is: {mse}")
    return

@task
def get_path(date=None):
    # use current day as default
    # train_path = current day - 2 months back & val_path = current day - 1 month back
    if date == None:

        date = datetime.date.today()

        train_path_date = date + relativedelta(months=-2)
        train_path_file_date = train_path_date.strftime('%Y-%m')
        val_path_date = date + relativedelta(months=-1)
        val_path_file_date = val_path_date.strftime('%Y-%m')

        train_path = glob.glob(f"./data/fhv_tripdata_{train_path_file_date}.parquet")[0]
        val_path = glob.glob(f"./data/fhv_tripdata_{val_path_file_date}.parquet")[0]

    else:
        # train_path = date - 2 months back & val_path = date - 1 month back
        # date = datetime.datetime.strptime(date, "%Y-%m-%d").date()

        train_path_date = date + relativedelta(months=-2)
        train_path_file_date = train_path_date.strftime('%Y-%m')
        val_path_date = date + relativedelta(months=-1)
        val_path_file_date = val_path_date.strftime('%Y-%m')

        train_path = glob.glob(f"./data/fhv_tripdata_{train_path_file_date}.parquet")[0]
        val_path = glob.glob(f"./data/fhv_tripdata_{val_path_file_date}.parquet")[0]
    
    return train_path, val_path
    
@flow(task_runner=SequentialTaskRunner())
def main(date="2021-08-15"): # train_path: str = './data/fhv_tripdata_2021-01.parquet', val_path: str = './data/fhv_tripdata_2021-02.parquet'):

    date = datetime.datetime.strptime(date, "%Y-%m-%d").date()

    train_path, val_path = get_path(date).result()

    categorical = ['PUlocationID', 'DOlocationID']

    df_train = read_data(train_path)
    df_train_processed = prepare_features(df_train, categorical)

    df_val = read_data(val_path)
    df_val_processed = prepare_features(df_val, categorical, False)

    # train the model
    lr, dv = train_model(df_train_processed, categorical).result()
    run_model(df_val_processed, categorical, dv, lr)

    with open(f"models/model-{date}.bin", 'wb') as f_out:
        pickle.dump((lr), f_out)

    with open(f"models/dv-{date}.bin", 'wb') as f_out:
        pickle.dump((dv), f_out)

    print(glob.glob('./models/*'))

main()

DeploymentSpec(
    flow=main,
    name="cron-schedule-deployment",
    flow_location="./homework.py",
    flow_runner=SubprocessFlowRunner(),
    schedule=CronSchedule(
        cron="0 9 15 * *",
        timezone="America/New_York")
)