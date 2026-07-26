from A_app0 import Ui_MainWindow
from PyQt5.QtWidgets import QFileDialog, QApplication,QTableWidgetItem,QTabWidget, QCheckBox,QGraphicsScene, QGraphicsPixmapItem, QGraphicsView,QMessageBox
import sys
import daojulogo
from tensorflow.keras.layers import GlobalAveragePooling2D, Dense, Input,Dropout,Flatten,MaxPooling2D,AveragePooling2D,ZeroPadding2D
from tensorflow.keras.models import Model
from tensorflow.keras.layers import Input, GlobalAveragePooling2D, Dense, Conv2D, Reshape, multiply,GlobalMaxPooling2D,GlobalAvgPool2D,UpSampling2D,concatenate,Activation, Lambda, Add, Permute, Concatenate,BatchNormalization
from tensorflow.keras.models import Model
from keras import backend as K
from keras.utils import plot_model
from PyQt5.QtWidgets import QFileDialog, QApplication,QTableWidgetItem,QTabWidget, QCheckBox,QGraphicsScene, QGraphicsPixmapItem, QGraphicsView
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QImage
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMainWindow,QWidget,QDialog
from PyQt5.QtCore import QCoreApplication, QThread, pyqtSignal,QMutex
import time
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from pathlib import Path
import os, PIL
import tensorflow as tf
from tensorflow.keras.callbacks import TensorBoard
from sklearn.model_selection import train_test_split
import glob
from tensorflow.keras.applications import InceptionV3,Xception,VGG16,VGG19,ResNet50,InceptionResNetV2,MobileNet,MobileNetV2,DenseNet121,DenseNet169,DenseNet201,NASNetMobile,NASNetLarge
import numpy as np
from tensorflow.keras.optimizers import Adam,SGD,Adadelta,Adagrad,Adamax,RMSprop,Nadam
np.random.seed(1)
import tensorflow as tf
tf.random.set_seed(1)
from PIL import Image

#from yuanxingchedao import train_py
import seaborn as sns
import os.path as path
import os
import matplotlib
import matplotlib.pyplot as plt
matplotlib.use("Qt5Agg")  # 声明使用QT5
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
import matplotlib.image as mpimg
import cv2
global singal

APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
ACCOUNT_FILE = APP_DIR / "A_chedaoyuce0.txt"

# from jiehe import Ui_ChildWindow
class EmittingStream(QtCore.QObject):
    textWritten = QtCore.pyqtSignal(str)  #定义一个发送str的信号
    def write(self, text):
        self.textWritten.emit(str(text))
    def flush(self):  # real signature unknown; restored from __doc__
        """ flush(self) """
        pass

class mainwindow(Ui_MainWindow,QMainWindow):
    def __init__(self):
        super().__init__()
        # 大概是继承了 Ui_MainWindow 的缘故，这里直接使用 setupUI()
        self.setupUi(self)
        # self.slot_init()  # 初始化槽函数
        self.show()
        sys.stdout = EmittingStream(textWritten=self.outputWritten)
        sys.stderr = EmittingStream(textWritten=self.outputWritten)
        self.timer_camera = QtCore.QTimer()  # 定义定时器，用于控制显示视频的帧率
        self.cap = cv2.VideoCapture()  # 视频流
        self.CAM_NUM = 0

        self.pushButton_4.clicked.connect(self.login)
        self.pushButton_11.clicked.connect(self.zero_page)
        self.pushButton_8.clicked.connect(self.register)
        self.pushButton_7.clicked.connect(self.turn_first_page)

        self.pushButton_18.clicked.connect(self.loadImage)
        self.pushButton_19.clicked.connect(self.start_training)
        self.pushButton.clicked.connect(self.stop_training)
        self.pushButton_20.clicked.connect(self.Image)
        # self.pushButton_5.clicked.connect(self.child.open)  # 关闭登录窗口
        self.pushButton_21.clicked.connect(self.save_json)  # 实现跳转的信号语句
        self.pushButton_6.clicked.connect(self.save_weight)
        self.pushButton_10.clicked.connect(self.second_page)
        self.pushButton_2.clicked.connect(self.first_page)
        self.pushButton_16.clicked.connect(self.openImage)
        self.pushButton_17.clicked.connect(self.preImage)
        self.pushButton_24.clicked.connect(self.open_Camera)
        self.timer_camera.timeout.connect(self.show_camera)  # 若定时器结束，则调用show_camera()
        self.pushButton_25.clicked.connect(self.pre_Camera)
        self.pushButton_28.clicked.connect(self.saveImage)
        self.pushButton_5.clicked.connect(self.Image_save)
        self.pushButton_26.clicked.connect(self.choose_weight)
        self.pushButton_27.clicked.connect(self.choose_json)
        self.pushButton_3.clicked.connect(self.clear_page)
        # self.pushButton_11.clicked.connect(self.main_page)
        self.pushButton_9.clicked.connect(self.clear_page0)
        self.pushButton_12.clicked.connect(self.fenge)
        self.pushButton_13.clicked.connect(self.fenge0)
        self.pushButton_14.clicked.connect(self.fenge_save)

    def zero_page(self):
        self.stackedWidget.setCurrentIndex(0)

    def register(self):
        username = self.lineEdit_3.text()
        password = self.lineEdit_8.text()
        confirm_password = self.lineEdit_9.text()
        if username and password and confirm_password:
            if password == confirm_password:
                QMessageBox.information(self, 'Success', 'Registered successfully')
                with ACCOUNT_FILE.open('a', encoding='utf-8') as file:
                    file.write(f'{username},{password}\n')
                self.stackedWidget.setCurrentIndex(0)
            else:
                QMessageBox.warning(self, 'Error', 'Passwords do not match')
        else:
            QMessageBox.warning(self, 'Error', 'Please fill in all fields')

    def login(self):
        s_username = self.lineEdit.text()
        s_password = self.lineEdit_2.text()
        with ACCOUNT_FILE.open('r', encoding='utf-8') as file:
            accounts = file.readlines()
        for account in accounts:
            saved_username, saved_password = account.strip().split(',')
            if saved_username == s_username and saved_password == s_password:
                self.stackedWidget.setCurrentIndex(2)
                return
        QMessageBox.warning(self, 'Error', '请确认账号密码')

    def turn_first_page(self):
        self.stackedWidget.setCurrentIndex(1)

    def first_page(self):
        self.stackedWidget.setCurrentIndex(2)

    def second_page(self):
        self.stackedWidget.setCurrentIndex(3)

    def clear_page(self):
        self.label_8.clear()
        self.label_11.clear()
        self.timer_camera.stop()  # 关闭定时器
        self.cap.release()  # 释放视频流
        self.label_7.clear()  # 清空视频显示区域

    def openImage(self):  # 选择本地图片上传
        global imgName  # 这里为了方便别的地方引用图片路径，我们把它设置为全局变量
        imgName, imgType = QFileDialog.getOpenFileName(self.centralwidget, "", "/",
                                                       "All Files(*)")  # 弹出一个文件选择框，第一个返回值imgName记录选中的文件路径+文件名，第二个返回值imgType记录文件的类型
        jpg = QtGui.QPixmap(imgName).scaled(self.label_7.width(),
                                            self.label_7.height())  # 通过文件路径获取图片文件，并设置图片长宽为label控件的长宽
        self.label_7.setPixmap(jpg)  # 在label控件上显示选择的图片
        self.lineEdit_5.setText(imgName)  # 显示所选图片的本地路径

    def choose_weight(self):
        global weight_h5
        weight_h5, weightType = QFileDialog.getOpenFileName(self.centralwidget, "选择文件", str(ARTIFACTS_DIR),
                                                            "All Files (*);;*.h5")
        self.lineEdit_6.setText(weight_h5)
        print(weight_h5)

    def choose_json(self):
        global json
        json, jsonType = QFileDialog.getOpenFileName(self.centralwidget, "选择文件", str(ARTIFACTS_DIR),
                                                     "All Files (*);;*.json")
        self.lineEdit_7.setText(json)
        print(json)

    def open_Camera(self):
        if self.timer_camera.isActive() == False:  # 若定时器未启动
                flag = self.cap.open(self.CAM_NUM)  # 参数是0，表示打开笔记本的内置摄像头，参数是视频文件路径则打开视频
                if flag == False:  # flag表示open()成不成功
                        msg = QtWidgets.QMessageBox.warning(self, 'warning', "请检查相机于电脑是否连接正确",
                                                            buttons=QtWidgets.QMessageBox.Ok)
                else:
                        self.timer_camera.start(30)  # 定时器开始计时30ms，结果是每过30ms从摄像头中取一帧显示
                        self.pushButton_24.setText('关闭摄像头')
        else:
                self.timer_camera.stop()  # 关闭定时器
                self.cap.release()  # 释放视频流
                self.label_7.clear()  # 清空视频显示区域
                self.pushButton_24.setText('打开摄像头')

    def show_camera(self):
        flag, self.image = self.cap.read()  # 从视频流中读取

        show = cv2.resize(self.image, (self.label_7.width(), self.label_7.height()))  # 把读到的帧的大小重新设置为 640x480
        show = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)  # 视频色彩转换回RGB，这样才是现实的颜色
        showImage = QtGui.QImage(show.data, show.shape[1], show.shape[0], show.shape[1] * 3,
                                 QtGui.QImage.Format_RGB888)  # 把读取到的视频数据变成QImage形式
        self.label_7.setPixmap(QtGui.QPixmap.fromImage(showImage))  # 往显示视频的Label里 显示QImage

    def fenge(self):
        global imgName
        global directory
        global weight_h5
        global json
        # lr = float(B)
        # N = globals()[C]
        IMAGEPATH = directory
        dirs = os.listdir(IMAGEPATH)

        json_file = open(json, 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        model = tf.keras.models.model_from_json(loaded_model_json)
        model.load_weights(weight_h5)

        w0 = 256
        import sys
        np.set_printoptions(threshold=sys.maxsize)

        input_image = cv2.imread(imgName)
        img0 = cv2.resize(input_image, (w0, w0), interpolation=cv2.INTER_AREA)

        img111 = cv2.cvtColor(img0, cv2.COLOR_BGR2RGB)
        gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
        gray00 = cv2.resize(gray0, (w0, w0), interpolation=cv2.INTER_AREA)
        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
        # out = clahe.apply(gray0)
        out = np.zeros(gray0.shape, np.uint8)
        cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
        gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        # ret, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        threshold_area = 4000
        tophat0 = np.zeros_like(binary)
        for (u, label) in enumerate(np.unique(labels)):
            # 如果是背景，忽略
            if label == 0:
                continue
            if stats[u][-1] > threshold_area:
                tophat0[labels == u] = 255
        kernel = np.ones((18, 18), np.uint8)
        kernel2 = np.ones((10, 10), np.uint8)
        tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
        # # cv2.imshow('t', tophat)
        # # cv2.waitKey(0)
        tophat = cv2.erode(tophat1, kernel2)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        threshold_area = 30000
        image_filtered = np.zeros_like(tophat)
        for (e, label) in enumerate(np.unique(labels)):
            # 如果是背景，忽略
            if label == 0:
                continue
            if stats[e][-1] > threshold_area:
                image_filtered[labels == e] = 255
        img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
        img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
        # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(16, 16))
        # enhanced_image = clahe.apply(img)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
        kernel0 = np.ones((14, 14), np.uint8)
        tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
        img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
        img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
        # enhanced_image = clahe.apply(img)
        enhanced_image = np.zeros(img.shape, np.uint8)
        cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
        # enhanced_image = clahe.apply(img)
        gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
        grayz = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
        # gray = clahe.apply(grayz)

        img4 = cv2.resize(grayz, (w0, w0), interpolation=cv2.INTER_AREA)
        x_seg = [gray00]

        x_seg = np.expand_dims(x_seg, axis=3)
        img_tensor = tf.convert_to_tensor(x_seg)
        x_seg = tf.image.grayscale_to_rgb(img_tensor)
        x_seg = np.asarray(x_seg)
        x_seg = x_seg.astype('float32')
        # input_array = x_seg / 255

        # 4. 进行预测
        input_array = x_seg / 255  # 归一化
        # input_array = np.expand_dims(input_array, axis=0)  # 添加批次维度
        predicted_mask = model.predict(input_array)[1]
        # 5. 处理预测结果
        # 假设预测结果的形状为 (1, HEIGHT, WIDTH, NUM_CLASSES)
        predicted_mask = np.argmax(predicted_mask, axis=-1)  # 获取每个像素的类标签
        prediction = predicted_mask[0]  # 去掉批次维度
        print(prediction.shape)
        # 将类别标签映射到 [0, 255] 范围
        # # 应用阈值
        # prediction = np.squeeze(prediction)
        # prediction[prediction >= 0.5] = 1
        # prediction[prediction < 0.5] = 0
        # 6. 保存/显示分割结果
        # 如果需要，可以将预测的掩码保存为图像
        segmented_image = Image.fromarray((prediction * 255).astype(np.uint8))

        def pil_to_qimage(pil_image):
            """Converts a PIL Image to QImage."""
            pil_image = pil_image.convert("RGBA")
            width, height = pil_image.size
            data = pil_image.tobytes("raw", "RGBA")
            q_img = QImage(data, width, height, QImage.Format_RGBA8888)
            return q_img

        q_img = pil_to_qimage(segmented_image)
        pixmap = QtGui.QPixmap.fromImage(q_img).scaled(self.label_11.width(), self.label_11.height(), Qt.KeepAspectRatio)
        self.label_11.setPixmap(pixmap)
        # print(segmented_image)
        # save_path = r"D:\pythonhuidu\mask"
        # # save_path =os.path.join(save_path, test_name)
        # segmented_image.save(save_path + '/' + '1.png', format='PNG')
        # segmented_image.save("D:\pythonhuidu\mask\pretict/47.png")

    def fenge0(self):
        global show
        global directory
        global weight_h5
        global json
        # lr = float(B)
        # N = globals()[C]
        IMAGEPATH = directory
        dirs = os.listdir(IMAGEPATH)

        json_file = open(json, 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        model = tf.keras.models.model_from_json(loaded_model_json)
        model.load_weights(weight_h5)

        w0 = 256
        import sys
        np.set_printoptions(threshold=sys.maxsize)
        if self.cap.isOpened():
            ret, show = self.cap.read()  # 从视频流中读取

            img0 = cv2.resize(show, (w0, w0), interpolation=cv2.INTER_AREA)

            img111 = cv2.cvtColor(img0, cv2.COLOR_BGR2RGB)
            gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
            gray00 = cv2.resize(gray0, (w0, w0), interpolation=cv2.INTER_AREA)
            # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
            # out = clahe.apply(gray0)
            out = np.zeros(gray0.shape, np.uint8)
            cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
            gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
            gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
            # ret, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
            binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
            areas = stats[:, cv2.CC_STAT_AREA]
            threshold_area = 4000
            tophat0 = np.zeros_like(binary)
            for (u, label) in enumerate(np.unique(labels)):
                # 如果是背景，忽略
                if label == 0:
                    continue
                if stats[u][-1] > threshold_area:
                    tophat0[labels == u] = 255
            kernel = np.ones((18, 18), np.uint8)
            kernel2 = np.ones((10, 10), np.uint8)
            tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
            # # cv2.imshow('t', tophat)
            # # cv2.waitKey(0)
            tophat = cv2.erode(tophat1, kernel2)
            num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
            areas = stats[:, cv2.CC_STAT_AREA]
            threshold_area = 30000
            image_filtered = np.zeros_like(tophat)
            for (e, label) in enumerate(np.unique(labels)):
                # 如果是背景，忽略
                if label == 0:
                    continue
                if stats[e][-1] > threshold_area:
                    image_filtered[labels == e] = 255
            img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
            img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
            # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(16, 16))
            # enhanced_image = clahe.apply(img)
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
            kernel0 = np.ones((14, 14), np.uint8)
            tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
            img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
            img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
            # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
            # enhanced_image = clahe.apply(img)
            enhanced_image = np.zeros(img.shape, np.uint8)
            cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
            # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
            # enhanced_image = clahe.apply(img)
            gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
            gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
            grayz = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
            # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
            # gray = clahe.apply(grayz)

            img4 = cv2.resize(grayz, (w0, w0), interpolation=cv2.INTER_AREA)
            x_seg = [gray00]

            x_seg = np.expand_dims(x_seg, axis=3)
            img_tensor = tf.convert_to_tensor(x_seg)
            x_seg = tf.image.grayscale_to_rgb(img_tensor)
            x_seg = np.asarray(x_seg)
            x_seg = x_seg.astype('float32')
            # input_array = x_seg / 255

            # 4. 进行预测
            input_array = x_seg / 255  # 归一化
            # input_array = np.expand_dims(input_array, axis=0)  # 添加批次维度
            predicted_mask = model.predict(input_array)[1]
            # 5. 处理预测结果
            # 假设预测结果的形状为 (1, HEIGHT, WIDTH, NUM_CLASSES)
            predicted_mask = np.argmax(predicted_mask, axis=-1)  # 获取每个像素的类标签
            prediction = predicted_mask[0]  # 去掉批次维度
            print(prediction.shape)
            # 将类别标签映射到 [0, 255] 范围
            # # 应用阈值
            # prediction = np.squeeze(prediction)
            # prediction[prediction >= 0.5] = 1
            # prediction[prediction < 0.5] = 0
            # 6. 保存/显示分割结果
            # 如果需要，可以将预测的掩码保存为图像
            segmented_image = Image.fromarray((prediction * 255).astype(np.uint8))

            def pil_to_qimage(pil_image):
                """Converts a PIL Image to QImage."""
                pil_image = pil_image.convert("RGBA")
                width, height = pil_image.size
                data = pil_image.tobytes("raw", "RGBA")
                q_img = QImage(data, width, height, QImage.Format_RGBA8888)
                return q_img

            q_img = pil_to_qimage(segmented_image)
            pixmap = QtGui.QPixmap.fromImage(q_img).scaled(self.label_11.width(), self.label_11.height(),
                                                           Qt.KeepAspectRatio)
            self.label_11.setPixmap(pixmap)
    def fenge_save(self):  # 保存图片到本地
        screen = QApplication.primaryScreen()
        pix = screen.grabWindow(self.label_11.winId())
        fd, type = QFileDialog.getSaveFileName(None, "保存图片", "", "*.jpg;;*.png;;All Files(*)")
        pix.save(fd)

    def pre_Camera(self):
        global show
        global directory
        global weight_h5
        global json
        IMAGEPATH = directory
        dirs = os.listdir(IMAGEPATH)

        json_file = open(json, 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        model = tf.keras.models.model_from_json(loaded_model_json)
        model.compile(loss=tf.keras.losses.categorical_crossentropy,
                      optimizer=tf.keras.optimizers.Adadelta(),
                      metrics=['accuracy'])
        model.load_weights(weight_h5)
        model.summary

        if self.cap.isOpened():
                ret, show = self.cap.read()  # 从视频流中读取
                primg = show
                h = int(primg.shape[0])
                w = int(primg.shape[1])
                width_new = 800
                height_new = int(h * width_new / w)
                img0 = cv2.resize(primg, (width_new, height_new), interpolation=cv2.INTER_AREA)
                gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
                out = np.zeros(gray0.shape, np.uint8)
                cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
                gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
                gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
                # cv2.imshow('gray', gray)
                # cv2.waitKey(0)

                binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                # cv2.imshow('gray', binary)
                # cv2.waitKey(0)

                num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
                areas = stats[:, cv2.CC_STAT_AREA]
                threshold_area = 4000
                tophat0 = np.zeros_like(binary)
                for (u, label) in enumerate(np.unique(labels)):
                    # 如果是背景，忽略
                    if label == 0:
                        continue
                    if stats[u][-1] > threshold_area:
                        tophat0[labels == u] = 255
                # cv2.imshow("image", tophat0)  # 显示图片，后面会讲解
                # cv2.waitKey(0)  # 等待按键

                kernel = np.ones((18, 18), np.uint8)
                kernel2 = np.ones((10, 10), np.uint8)
                tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
                # # cv2.imshow('t', tophat)
                # # cv2.waitKey(0)
                tophat = cv2.erode(tophat1, kernel2)
                num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
                areas = stats[:, cv2.CC_STAT_AREA]
                threshold_area = 30000
                image_filtered = np.zeros_like(tophat)
                for (e, label) in enumerate(np.unique(labels)):
                    # 如果是背景，忽略
                    if label == 0:
                        continue
                    if stats[e][-1] > threshold_area:
                        image_filtered[labels == e] = 255
                img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
                # for path3,b in zip(file_paths,range(image_count)):
                # img = cv2.resize(path3, (w, h), interpolation=cv2.INTER_AREA)
                img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
                # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(12, 12))
                # enhanced_image = clahe.apply(img)

                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                kernel0 = np.ones((13, 13), np.uint8)
                tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
                img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
                img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
                # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(12, 12))
                # enhanced_image = clahe.apply(img)
                enhanced_image = np.zeros(img.shape, np.uint8)
                cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
                # enhanced_image = clahe.apply(img)
                gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
                gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
                gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

                # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
                # gray = clahe.apply(gray)

                img4 = cv2.resize(gray, (299, 299), interpolation=cv2.INTER_AREA)
                img = cv2.cvtColor(img4, cv2.COLOR_BGR2RGB)

                img = cv2.resize(img, (299, 299), interpolation=cv2.INTER_AREA)
                # img_gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                # cv2.imwrite(path1 , img)  # 保存
                img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                # cv2.imwrite(path1 + ".jpg", img)  # 保存
                # cv2.imshow("image", img)  # 显示图片，后面会讲解
                # cv2.waitKey(0)  # 等待按键

                x_test = np.asarray(img)
                x_test = x_test.astype('float32')
                x_test = x_test / 255
                x_test = x_test.reshape(1, 299, 299, 3)
                # img = img.reshape((1,299,299,3))
                predict = model.predict(x_test)

                img = x_test
                img = img.reshape(299, 299, 3)
                img = img * 255
                img = img.astype('uint8')
                img = cv2.resize(img, (299, 299), interpolation=cv2.INTER_AREA)
                im_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                i = np.argmax(predict)
                str1 = dirs[i] + " " + str(predict[0][i])
                print(str1)
                cv2.putText(img0, str1, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 1, cv2.LINE_AA)
                q_img = QtGui.QImage(img0.data, img0.shape[1], img0.shape[0],
                                     img0.shape[0] * img0.shape[2],
                                     QtGui.QImage.Format_RGB888)  #
                im = QtGui.QPixmap(q_img).scaled(self.label_8.width(),
                                                 self.label_8.height())
                self.label_8.setPixmap(im)

    def preImage(self):
        global imgName
        global directory
        global weight_h5
        global json
        # lr = float(B)
        # N = globals()[C]
        IMAGEPATH = directory
        dirs = os.listdir(IMAGEPATH)

        json_file = open(json, 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        model = tf.keras.models.model_from_json(loaded_model_json)
        model.compile(loss=tf.keras.losses.categorical_crossentropy,
                      optimizer=Adadelta(learning_rate=0.0001),
                      metrics=['accuracy'])
        model.load_weights(weight_h5)
        model.summary

        image_dir = imgName
        primg = cv2.imread(image_dir)
        h = int(primg.shape[0])
        w = int(primg.shape[1])
        width_new = 800
        height_new = int(h * width_new / w)
        img0 = cv2.resize(primg, (width_new, height_new), interpolation=cv2.INTER_AREA)
        gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
        out = np.zeros(gray0.shape, np.uint8)
        cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
        gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
        # cv2.imshow('gray', gray)
        # cv2.waitKey(0)

        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
        # cv2.imshow('gray', binary)
        # cv2.waitKey(0)

        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        threshold_area = 4000
        tophat0 = np.zeros_like(binary)
        for (u, label) in enumerate(np.unique(labels)):
            # 如果是背景，忽略
            if label == 0:
                continue
            if stats[u][-1] > threshold_area:
                tophat0[labels == u] = 255
        # cv2.imshow("image", tophat0)  # 显示图片，后面会讲解
        # cv2.waitKey(0)  # 等待按键

        kernel = np.ones((18, 18), np.uint8)
        kernel2 = np.ones((10, 10), np.uint8)
        tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
        # # cv2.imshow('t', tophat)
        # # cv2.waitKey(0)
        tophat = cv2.erode(tophat1, kernel2)
        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
        areas = stats[:, cv2.CC_STAT_AREA]
        threshold_area = 30000
        image_filtered = np.zeros_like(tophat)
        for (e, label) in enumerate(np.unique(labels)):
            # 如果是背景，忽略
            if label == 0:
                continue
            if stats[e][-1] > threshold_area:
                image_filtered[labels == e] = 255
        img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
        # for path3,b in zip(file_paths,range(image_count)):
        # img = cv2.resize(path3, (w, h), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
        # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(12, 12))
        # enhanced_image = clahe.apply(img)

        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
        kernel0 = np.ones((13, 13), np.uint8)
        tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
        img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
        img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(12, 12))
        # enhanced_image = clahe.apply(img)
        enhanced_image = np.zeros(img.shape, np.uint8)
        cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
        # enhanced_image = clahe.apply(img)
        gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
        # gray = clahe.apply(gray)

        img4 = cv2.resize(gray, (299, 299), interpolation=cv2.INTER_AREA)
        img = cv2.cvtColor(img4, cv2.COLOR_BGR2RGB)

        img = cv2.resize(img, (299, 299), interpolation=cv2.INTER_AREA)
        # img_gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        # cv2.imwrite(path1 , img)  # 保存
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        # cv2.imwrite(path1 + ".jpg", img)  # 保存
        # cv2.imshow("image", img)  # 显示图片，后面会讲解
        # cv2.waitKey(0)  # 等待按键

        x_test = np.asarray(img)
        x_test = x_test.astype('float32')
        x_test = x_test / 255
        x_test = x_test.reshape(1, 299, 299, 3)
        # img = img.reshape((1,299,299,3))
        predict = model.predict(x_test)

        img = x_test
        img = img.reshape(299, 299, 3)
        img = img * 255
        img = img.astype('uint8')
        img = cv2.resize(img0, (299, 299), interpolation=cv2.INTER_AREA)
        im_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        i = np.argmax(predict)
        print(i)
        str1 = dirs[1] + " " + str(predict[0][i])
        print(str1)
        cv2.putText(im_bgr,str1, (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        q_img = QtGui.QImage(im_bgr.data, im_bgr.shape[1], im_bgr.shape[0], im_bgr.shape[0] * im_bgr.shape[2],
                             QtGui.QImage.Format_RGB888)  #
        im = QtGui.QPixmap(q_img).scaled(self.label_8.width(),
                                         self.label_8.height())
        self.label_8.setPixmap(im)

    def saveImage(self):  # 保存图片到本地
        screen = QApplication.primaryScreen()
        pix = screen.grabWindow(self.label_8.winId())
        fd, type = QFileDialog.getSaveFileName(None, "保存图片", "", "*.jpg;;*.png;;All Files(*)")
        pix.save(fd)

    def save_json(self):
        global model
        filepath1, type = QFileDialog.getSaveFileName(None, '文件保存', '', "*.json;;All Files(*)")
        if filepath1 == filepath1:
                    pass  # 防止关闭或取消导入关闭所有页面
        else:
             with open(filepath1, "w") as json_file:
                            json_file.write(model.to_json())

    def save_weight(self):
        global model
        filepath2, type = QFileDialog.getSaveFileName(None, '文件保存', '', '*.h5;;All Files(*)')

        if filepath2 == filepath2:
                    pass  # 防止关闭或取消导入关闭所有页面
        else:
                model.save_weights(filepath2)

    def loadImage(self):
        global directory
        directory = QFileDialog.getExistingDirectory(None, "选取文件夹")
        self.lineEdit_4.setText(directory)
        print(directory)

    def start_training(self):
        self.thread = Runthread()
        global A
        global B
        global C
        global D
        global E
        A = self.spinBox.value()
        B = self.doubleSpinBox.value()
        C = self.comboBox_12.currentText()
        D = self.comboBox_11.currentText()
        E = self.spinBox_2.value()
        self.thread.start()

    def Image(self):
        global con_matValue
        global history
        figure3 = plt.figure(figsize=(5, 5))
        sns.heatmap(con_matValue, annot=True, cmap=plt.cm.Blues)
        plt.tight_layout(pad=2.0)
        plt.title('Confusion Matrix')
        plt.ylabel('True label')
        plt.xlabel('Predicted label')

        figure1 = plt.figure(figsize=(5, 5))
        plt.subplot(1, 1, 1)
        plt.plot(history.history['accuracy'], label='Training Accuracy')
        plt.plot(history.history['val_accuracy'], label='Validation Accuracy')
        plt.xlabel('Epoch')
        plt.ylabel('Accuracy')
        plt.title('Training and Validation Accuracy')
        plt.legend()
        figure2 = plt.figure(figsize=(5, 5))
        plt.subplot(1, 1, 1)
        plt.plot(history.history['loss'], label='Training Loss')
        plt.plot(history.history['val_loss'], label='Validation Loss')
        plt.xlabel('Epoch')
        plt.ylabel('Loss')
        plt.title('Training and Validation Loss')
        plt.legend()
        # plt.show()

        figure1.canvas.draw()
        # Get the RGBA buffer from the figure
        w, h = figure1.canvas.get_width_height()
        buf = np.frombuffer(figure1.canvas.tostring_argb(), dtype=np.uint8)
        buf.shape = (w, h, 4)

        # canvas.tostring_argb give pixmap in ARGB mode. Roll the ALPHA channel to have it in RGBA mode
        buf = np.roll(buf, 3, axis=2)
        image = Image.frombytes("RGBA", (w, h), buf.tobytes())
        image = np.asarray(image)

        # cv2.imshow("image", image)
        # cv2.waitKey(0)
        show = cv2.resize(image, (self.label_23.width(), self.label_23.height()))  # 把读到的帧的大小重新设置为 640x480
        image = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        q_img = QtGui.QImage(image.data, image.shape[1], image.shape[0], image.shape[1] * 3,
                             QtGui.QImage.Format_RGB888)
        im = QtGui.QPixmap(q_img).scaled(self.label_23.width(),
                                         self.label_23.height())
        self.label_23.setPixmap(im)

        figure2.canvas.draw()
        # Get the RGBA buffer from the figure
        w, h = figure2.canvas.get_width_height()
        buf = np.frombuffer(figure2.canvas.tostring_argb(), dtype=np.uint8)
        buf.shape = (w, h, 4)

        # canvas.tostring_argb give pixmap in ARGB mode. Roll the ALPHA channel to have it in RGBA mode
        buf = np.roll(buf, 3, axis=2)
        image = Image.frombytes("RGBA", (w, h), buf.tobytes())
        image = np.asarray(image)

        # cv2.imshow("image", image)
        # cv2.waitKey(0)
        show = cv2.resize(image, (self.label_22.width(), self.label_22.height()))  # 把读到的帧的大小重新设置为 640x480
        image = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        q_img = QtGui.QImage(image.data, image.shape[1], image.shape[0], image.shape[1] * 3,
                             QtGui.QImage.Format_RGB888)
        im = QtGui.QPixmap(q_img).scaled(self.label_22.width(),
                                         self.label_22.height())
        self.label_22.setPixmap(im)

        figure3.canvas.draw()
        # Get the RGBA buffer from the figure
        w, h = figure1.canvas.get_width_height()
        buf = np.frombuffer(figure3.canvas.tostring_argb(), dtype=np.uint8)
        buf.shape = (w, h, 4)

        # canvas.tostring_argb give pixmap in ARGB mode. Roll the ALPHA channel to have it in RGBA mode
        buf = np.roll(buf, 3, axis=2)
        image = Image.frombytes("RGBA", (w, h), buf.tobytes())
        image = np.asarray(image)

        # cv2.imshow("image", image)
        # cv2.waitKey(0)
        show = cv2.resize(image, (self.label_21.width(), self.label_21.height()))  # 把读到的帧的大小重新设置为 640x480
        image = cv2.cvtColor(show, cv2.COLOR_BGR2RGB)
        q_img = QtGui.QImage(image.data, image.shape[1], image.shape[0], image.shape[1] * 3,
                             QtGui.QImage.Format_RGB888)
        im = QtGui.QPixmap(q_img).scaled(self.label_21.width(),
                                         self.label_21.height())
        self.label_21.setPixmap(im)

    def Image_save(self):
        screen = QApplication.primaryScreen()
        list = [self.label_23.winId(), self.label_22.winId(), self.label_21.winId()]
        for i in list:
                pix1 = screen.grabWindow(i)
                # pix2 = screen.grabWindow(self.label_22.winId())
                # pix3 = screen.grabWindow(self.label_21.winId())
                fd, type = QFileDialog.getSaveFileName(self.centralwidget, "保存图片", "",
                                                       "*.jpg;;*.png;;All Files(*)")
                pix1.save(fd)
        # pix2.save(fd)
        # pix3.save(fd)

    def stop_training(self):
        self.thread.terminate()
    def clear_page0(self):
        self.label_21.clear()
        self.label_22.clear()
        self.label_23.clear()
        self.textEdit_4.clear()
        # def open(self):
        #     self.label_5.clear()
        #     self.label_6.clear()
        #     self.textEdit.clear()
        #     self.child=Child()
        # self.child.setupUi(QMainWindow)
        # self.child.show()
        # def close_window(self):
        #     MainWindow.close()  # 关闭的时候要用窗口的实例化对象来关闭，不能用self

    def outputWritten(self, text):
        cursor = self.textEdit_4.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        cursor.insertText(text)
        self.textEdit_4.setTextCursor(cursor)
        self.textEdit_4.ensureCursorVisible()

class Runthread(QThread):
    sinOut = pyqtSignal(str)

    def __init__(self):
            super(Runthread, self).__init__()


    def run(self):
            global directory
            global history
            global model
            global con_matValue
            epoch = int(A)
            lr = float(B)
            Bs = int(E)
            print(epoch)
            print(Bs)
            print(lr)
            print(C)
            print(D)
            # epoch = int(A)
            # lr = float(B)
            N = globals()[C]
            M = globals()[D]

            if M==Xception:
                # 通道注意力机制
                def channel_attention(input_feature, ratio=2):
                    channel_axis = 1 if K.image_data_format() == "channels_first" else -1
                    channel = input_feature.shape[channel_axis]

                    shared_layer_one = Dense(channel // ratio,
                                             kernel_initializer='he_normal',
                                             activation='relu',
                                             use_bias=True,
                                             bias_initializer='zeros')

                    shared_layer_two = Dense(channel,
                                             activation='sigmoid',
                                             kernel_initializer='he_normal',
                                             use_bias=True,
                                             bias_initializer='zeros')

                    avg_pool = GlobalAveragePooling2D()(input_feature)
                    avg_pool = Reshape((1, 1, channel))(avg_pool)
                    assert avg_pool.shape[1:] == (1, 1, channel)
                    avg_pool = shared_layer_one(avg_pool)
                    assert avg_pool.shape[1:] == (1, 1, channel // ratio)
                    avg_pool = shared_layer_two(avg_pool)
                    assert avg_pool.shape[1:] == (1, 1, channel)

                    max_pool = GlobalMaxPooling2D()(input_feature)
                    max_pool = Reshape((1, 1, channel))(max_pool)
                    assert max_pool.shape[1:] == (1, 1, channel)
                    max_pool = shared_layer_one(max_pool)
                    assert max_pool.shape[1:] == (1, 1, channel // ratio)
                    max_pool = shared_layer_two(max_pool)
                    assert max_pool.shape[1:] == (1, 1, channel)

                    cbam_feature = Add()([avg_pool, max_pool])
                    cbam_feature = Activation('hard_sigmoid')(cbam_feature)

                    if K.image_data_format() == "channels_first":
                        cbam_feature = Permute((3, 1, 2))(cbam_feature)

                    return multiply([input_feature, cbam_feature])

                # 空间注意力机制
                def spatial_attention(input_feature):
                    kernel_size = 7

                    if K.image_data_format() == "channels_first":
                        channel = input_feature.shape[1]
                        cbam_feature = Permute((2, 3, 1))(input_feature)
                    else:
                        channel = input_feature.shape[-1]
                        cbam_feature = input_feature

                    # avg_pool = Lambda(lambda x: K.mean(x, axis=3, keepdims=True))(cbam_feature)
                    # assert avg_pool.shape[-1] == 1
                    # max_pool = Lambda(lambda x: K.max(x, axis=3, keepdims=True))(cbam_feature)
                    # assert max_pool.shape[-1] == 1
                    # concat = Concatenate(axis=3)([avg_pool, max_pool])
                    # assert concat.shape[-1] == 2
                    avg_pool = K.mean(cbam_feature, axis=3, keepdims=True)
                    assert avg_pool.shape[-1] == 1
                    max_pool = K.max(cbam_feature, axis=3, keepdims=True)
                    assert max_pool.shape[-1] == 1
                    concat = Concatenate(axis=3)([avg_pool, max_pool])
                    assert concat.shape[-1] == 2
                    cbam_feature = Conv2D(filters=1,
                                          kernel_size=kernel_size,
                                          activation='hard_sigmoid',
                                          strides=1,
                                          padding='same',
                                          kernel_initializer='he_normal',
                                          use_bias=False)(concat)
                    assert cbam_feature.shape[-1] == 1

                    if K.image_data_format() == "channels_first":
                        cbam_feature = Permute((3, 1, 2))(cbam_feature)

                    return multiply([input_feature, cbam_feature])

                # 构建CBA
                def cbam_block(cbam_feature, ratio=2):
                    """Contains the implementation of Convolutional Block Attention Module(CBAM) block.
                    As described in https://arxiv.org/abs/1807.06521.
                    """
                    cbam_feature = channel_attention(cbam_feature, ratio)
                    cbam_feature = spatial_attention(cbam_feature, )
                    return cbam_feature


                start = time.perf_counter()
                conv_base = M(weights='imagenet', include_top=False, input_tensor=Input(shape=(299, 299, 3)))
                conv_base.summary()

                IMAGEPATH = str(PROJECT_ROOT / 'data' / 'images')
                dirs = os.listdir(IMAGEPATH)
                count = len(os.listdir(IMAGEPATH))
                print("图片分类总数为：", count)
                X = []
                Y = []
                w0 = 299
                h0 = 299
                i = 0
                for name in dirs:
                    file_paths = glob.glob(path.join(IMAGEPATH + "/" + name, '*.*'))
                    image_count = len(file_paths)
                    print(name)
                    print(image_count)
                    # os.makedirs("D:\\pythontest\\newzzzz\\" + name)
                    for path3 in file_paths:
                        path3 = cv2.imread(path3)
                        # img2 = cv2.imread(path3, cv2.IMREAD_GRAYSCALE)
                        h = int(path3.shape[0])
                        w = int(path3.shape[1])
                        width_new = 800
                        height_new = int(h * width_new / w)
                        img0 = cv2.resize(path3, (width_new, width_new), interpolation=cv2.INTER_AREA)
                        gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
                        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
                        # out = clahe.apply(gray0)
                        out = np.zeros(gray0.shape, np.uint8)
                        cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                        gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
                        gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
                        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
                        # ret, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
                        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
                        areas = stats[:, cv2.CC_STAT_AREA]
                        threshold_area = 4000
                        tophat0 = np.zeros_like(binary)
                        for (u, label) in enumerate(np.unique(labels)):
                            # 如果是背景，忽略
                            if label == 0:
                                continue
                            if stats[u][-1] > threshold_area:
                                tophat0[labels == u] = 255
                        kernel = np.ones((18, 18), np.uint8)
                        kernel2 = np.ones((10, 10), np.uint8)
                        tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
                        # # cv2.imshow('t', tophat)
                        # # cv2.waitKey(0)
                        tophat = cv2.erode(tophat1, kernel2)
                        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
                        areas = stats[:, cv2.CC_STAT_AREA]
                        threshold_area = 30000
                        image_filtered = np.zeros_like(tophat)
                        for (e, label) in enumerate(np.unique(labels)):
                            # 如果是背景，忽略
                            if label == 0:
                                continue
                            if stats[e][-1] > threshold_area:
                                image_filtered[labels == e] = 255
                        img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
                        # for path3,b in zip(file_paths,range(image_count)):
                        # img = cv2.resize(path3, (w, h), interpolation=cv2.INTER_AREA)
                        img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
                        # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                        kernel0 = np.ones((13, 13), np.uint8)
                        tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
                        img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
                        img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
                        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        enhanced_image = np.zeros(img.shape, np.uint8)
                        cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
                        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
                        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

                        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
                        # gray = clahe.apply(gray)

                        img4 = cv2.resize(gray, (w0, h0), interpolation=cv2.INTER_AREA)
                        img = cv2.cvtColor(img4, cv2.COLOR_BGR2RGB)
                        # cv2.imshow("W0", img)
                        # cv2.waitKey(delay=0)
                        # cv2.imwrite("D:\\pythontest\\newzzzz\\" + name + "\\" + str(b) + ".jpg", im_rgb)# 保存
                        # cv2.imshow("image", im_rgb)  # 显示图片，后面会讲解
                        # cv2.waitKey(0)  # 等待按键
                        # cv2.destroyAllWindows()            #破坏我们创建的所有窗口
                        X.append(img)
                        Y.append(i)
                    i = i + 1

                x_train = np.asarray(X)
                print(x_train.shape)
                y_train = np.asarray(Y)
                x_train = x_train.astype('float32')
                x_train = x_train / 255
                print(x_train.shape)
                print(x_train.shape[0])
                # x_train=x_train.reshape(x_train.shape[0],w,h,3);
                x_train = x_train.reshape(x_train.shape[0], w0, h0, 3)
                category = count
                dim = x_train.shape[1]
                x_train, x_test, y_train, y_test = train_test_split(x_train, y_train, test_size=0.2)
                print('x_train shape:', x_train.shape)
                print('x_train shape:', y_train.shape)
                print('x_train shape:', x_test.shape)
                print('x_train shape:', y_test.shape)
                print(x_train.shape[0], 'train samples')
                print(x_test.shape[0], 'test samples')
                # 將數字轉為 One-hot 向量
                print(type(x_train), type(y_train))
                y_train2 = tf.keras.utils.to_categorical(y_train, category)
                y_test2 = tf.keras.utils.to_categorical(y_test, category)
                print(x_train.shape)
                print(y_test2)

                datagen = tf.keras.preprocessing.image.ImageDataGenerator(
                    rotation_range=45,
                    width_shift_range=[-20, 20],
                    height_shift_range=[-20, 20],
                    horizontal_flip=True,
                    vertical_flip=True,
                    data_format='channels_last')

                for layers in conv_base.layers[:-12]:
                    layers.trainable = False

                # 构建FPN模块
                C1, C2, C3, C4, C5 = conv_base.get_layer('block1_conv1').output, conv_base.get_layer(
                    'block3_sepconv1').output, conv_base.get_layer('block4_sepconv1').output, conv_base.get_layer(
                    'block10_sepconv1').output, conv_base.output
                print(C1.shape, C2.shape, C3.shape, C4.shape,
                      C5.shape)  # ,conv_base.get_layer('block10_sepconv1').output,C6.shape
                # 添加注意力模块
                attention_layer_1 = cbam_block(C1)
                attention_layer_2 = cbam_block(C2)
                attention_layer_3 = cbam_block(C3)
                attention_layer_4 = cbam_block(C4)
                attention_layer_5 = cbam_block(C5)
                # attention_layer_6 = cbam_block(C6)
                attention_layer_5 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_5)
                # attention_layer_5 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_5)
                # attention_layer_5=MaxPooling2D(pool_size=(2, 2),strides=2,padding='same')(attention_layer_5)
                attention_layer_4 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_4)
                attention_layer_4 = MaxPooling2D(pool_size=(2, 2), strides=2, padding='same')(attention_layer_4)
                attention_layer_3 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_3)
                attention_layer_3 = MaxPooling2D(pool_size=(4, 4), strides=4, padding='same')(attention_layer_3)
                attention_layer_2 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_2)
                attention_layer_2 = MaxPooling2D(pool_size=(8, 8), strides=8, padding='same')(attention_layer_2)
                attention_layer_1 = Conv2D(256, (1, 1), activation='relu', padding='same')(attention_layer_1)
                attention_layer_1 = MaxPooling2D(pool_size=(16, 16), strides=16, padding='same')(attention_layer_1)
                print(attention_layer_1.shape, attention_layer_2.shape, attention_layer_3.shape, attention_layer_4.shape,
                      attention_layer_5.shape)

                x = concatenate(
                    [attention_layer_5, attention_layer_1, attention_layer_2, attention_layer_3, attention_layer_4], axis=3)
                x = Conv2D(256, (1, 1), activation='relu', padding='same')(x)
                x = GlobalAveragePooling2D()(x)
                x = Dropout(rate=0.5)(x)
                # 添加一个全连接层
                x = Flatten()(x)
                x = Dense(128, activation='relu')(x)
                x = Dense(256, activation='relu')(x)
                # x = Dense(256, activation='relu')(x)

                # 添加最终的密集层，输出类别预测
                predictions = Dense(category, activation='softmax')(x)

                # 构建新模型
                model = Model(inputs=conv_base.input, outputs=predictions)
                model.summary()
                # # 画出模型结构图并保存为图片
                # plot_model(model, to_file='D:\pythonhuidu/chuli/xception_cbam2_model.png', show_shapes=True,
                #            show_layer_names=True)

                # 設定模型的 Loss 函數、Optimizer 以及用來判斷模型好壞的依據（metrics）
                model.compile(loss=tf.keras.losses.categorical_crossentropy,
                              optimizer=N(learning_rate=lr, weight_decay=0.00001),
                              metrics=['accuracy', tf.keras.metrics.Recall()])

                # 可训练层
                for o in model.trainable_weights:
                    print(o.name)
                print('\n')

                # 不可训练层
                for i in model.non_trainable_weights:
                    print(i.name)
                print('\n')

                tensorboard = TensorBoard(log_dir="logs")
                traindata = datagen.flow(x_train, y_train2, batch_size=Bs)
                testdata = datagen.flow(x_test, y_test2, batch_size=Bs)
                print('x_train shape:', x_train.shape)
                print('x_train shape:', y_train.shape)
                print('x_train shape:', x_test.shape)
                print('x_train shape:', y_test.shape)
                # 訓練模型
                history = model.fit(traindata, validation_data=(testdata), validation_freq=1,
                                    epochs=epoch,
                                    batch_size=Bs,
                                    verbose=1)

                # 測試
                score = model.evaluate(x_test, y_test2)
                # 輸出結果
                print("score:", score)

                predict = model.predict(x_test)
                print(predict)
                print("Ans:", np.argmax(predict[0]), np.argmax(predict[1]), np.argmax(predict[2]), np.argmax(predict[3]))

                predict2 = model.predict(x_test)
                predict2 = np.argmax(predict2, axis=1)
                print("predict_classes:", predict2[:20])
                print("y_test", y_test[:20])

                predict3 = model.predict(x_train)
                predict3 = np.argmax(predict3, axis=1)

                end = time.perf_counter()
                print('Running time: %s Seconds' % (end - start))

                tf.compat.v1.disable_eager_execution()
                con_mat = tf.math.confusion_matrix(labels=y_test, predictions=predict2,
                                                   dtype=tf.int32, name=None)
                with tf.compat.v1.Session():
                    con_matValue = tf.Tensor.eval(con_mat, feed_dict=None, session=None)
                    print('Confusion Matrix: \n\n', con_matValue)
            else:
                start = time.perf_counter()
                conv_base = M(input_shape=(299, 299, 3), weights='imagenet', include_top=False)
                conv_base.summary()

                IMAGEPATH = str(PROJECT_ROOT / 'data' / 'images')
                dirs = os.listdir(IMAGEPATH)
                count = len(os.listdir(IMAGEPATH))
                print("图片分类总数为：", count)
                X = []
                Y = []
                w0 = 299  # 224
                h0 = 299  # 224
                i = 0
                for name in dirs:
                    file_paths = glob.glob(path.join(IMAGEPATH + "/" + name, '*.*'))
                    image_count = len(file_paths)
                    print(name)
                    print(image_count)
                    # os.makedirs("D:\\pythontest\\newzzzz\\" + name)
                    for path3 in file_paths:
                        path3 = cv2.imread(path3)
                        # img2 = cv2.imread(path3, cv2.IMREAD_GRAYSCALE)
                        h = int(path3.shape[0])
                        w = int(path3.shape[1])
                        width_new = 800
                        height_new = int(h * width_new / w)
                        img0 = cv2.resize(path3, (width_new, width_new), interpolation=cv2.INTER_AREA)
                        gray0 = cv2.cvtColor(img0, cv2.COLOR_BGR2GRAY)
                        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
                        # out = clahe.apply(gray0)
                        out = np.zeros(gray0.shape, np.uint8)
                        cv2.normalize(gray0, out, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                        gray_img = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
                        gray = cv2.convertScaleAbs(gray_img, alpha=1.8, beta=10)
                        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
                        # ret, binary = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
                        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)
                        areas = stats[:, cv2.CC_STAT_AREA]
                        threshold_area = 4000
                        tophat0 = np.zeros_like(binary)
                        for (u, label) in enumerate(np.unique(labels)):
                            # 如果是背景，忽略
                            if label == 0:
                                continue
                            if stats[u][-1] > threshold_area:
                                tophat0[labels == u] = 255
                        kernel = np.ones((18, 18), np.uint8)
                        kernel2 = np.ones((10, 10), np.uint8)
                        tophat1 = cv2.dilate(tophat0, kernel)  # 膨胀
                        # # cv2.imshow('t', tophat)
                        # # cv2.waitKey(0)
                        tophat = cv2.erode(tophat1, kernel2)
                        num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(tophat, connectivity=8)
                        areas = stats[:, cv2.CC_STAT_AREA]
                        threshold_area = 30000
                        image_filtered = np.zeros_like(tophat)
                        for (e, label) in enumerate(np.unique(labels)):
                            # 如果是背景，忽略
                            if label == 0:
                                continue
                            if stats[e][-1] > threshold_area:
                                image_filtered[labels == e] = 255
                        img_mask = cv2.bitwise_and(img0, img0, mask=image_filtered)
                        # mask = np.zeros(img_mask.shape[:2], np.uint8)
                        # # rect = (int(r[0]), int(r[1]), int(r[2]), int(r[3]))
                        # img_x = img_mask.shape[1]
                        # img_y = img_mask.shape[0]
                        # # 分割的矩形区域
                        # rect = (10, 10, img_x, img_y)
                        # # 背景模式,必须为1行,13x5列
                        # bgModel = np.zeros((1, 65), np.float64)
                        # # 前景模式,必须为1行,13x5列
                        # fgModel = np.zeros((1, 65), np.float64)
                        # # # 图像掩模,取值有0,1,2,3
                        # # mask = np.zeros(img1.shape[:2], np.uint8)
                        # # grabCut处理,GC_INIT_WITH_RECT模式
                        # cv2.grabCut(img_mask, mask, rect, bgModel, fgModel, 4, cv2.GC_INIT_WITH_RECT)
                        # # grabCut处理,GC_INIT_WITH_MASK模式
                        # # cv2.grabCut(img1, mask, rect, bgModel, fgModel, 6, cv2.GC_INIT_WITH_MASK)
                        # # 将背景0,2设成0,其余设成1
                        # mask2 = np.where((mask == 2) | (mask == 0), 0, 1).astype('uint8')
                        # # 重新计算图像着色,对应元素相乘
                        # img3 = img_mask * mask2[:, :, np.newaxis]
                        # gray = cv2.cvtColor(img3, cv2.COLOR_BGR2GRAY)
                        # im_rgb = cv2.cvtColor(gray, cv2.COLOR_BGR2RGB)
                        # for path3,b in zip(file_paths,range(image_count)):
                        # img = cv2.resize(path3, (w, h), interpolation=cv2.INTER_AREA)
                        img = cv2.cvtColor(img_mask, cv2.COLOR_BGR2GRAY)
                        # im_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        # clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        gray1 = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        binary1 = cv2.adaptiveThreshold(gray1, 255, cv2.ADAPTIVE_THRESH_MEAN_C, 1, 11, 10)
                        kernel0 = np.ones((13, 13), np.uint8)
                        tophat1 = cv2.dilate(binary1, kernel0)  # 膨胀
                        img_mask1 = cv2.bitwise_and(gray_img, gray_img, mask=tophat1)
                        img = cv2.cvtColor(img_mask1, cv2.COLOR_BGR2GRAY)
                        # clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        enhanced_image = np.zeros(img.shape, np.uint8)
                        cv2.normalize(img, enhanced_image, 255, 0, cv2.NORM_MINMAX, cv2.CV_8U)
                        # clahe = cv2.createCLAHE(clipLimit=1.0, tileGridSize=(16, 16))
                        # enhanced_image = clahe.apply(img)
                        gray = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2RGB)
                        gray = cv2.convertScaleAbs(gray, alpha=1.5, beta=0)
                        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)

                        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(16, 16))
                        gray = clahe.apply(gray)

                        img4 = cv2.resize(gray, (w0, h0), interpolation=cv2.INTER_AREA)
                        img = cv2.cvtColor(img4, cv2.COLOR_BGR2RGB)
                        # cv2.imshow("W0", img)
                        # cv2.waitKey(delay=0)
                        # cv2.imwrite("D:\\pythontest\\newzzzz\\" + name + "\\" + str(b) + ".jpg", im_rgb)# 保存
                        # cv2.imshow("image", im_rgb)  # 显示图片，后面会讲解
                        # cv2.waitKey(0)  # 等待按键
                        # cv2.destroyAllWindows()            #破坏我们创建的所有窗口
                        X.append(img)
                        Y.append(i)
                    i = i + 1

                x_train = np.asarray(X)
                print(x_train.shape)
                y_train = np.asarray(Y)
                x_train = x_train.astype('float32')
                x_train = x_train / 255
                print(x_train.shape)
                print(x_train.shape[0])
                # x_train=x_train.reshape(x_train.shape[0],w,h,3);
                x_train = x_train.reshape(x_train.shape[0], w0, h0, 3)
                category = count
                dim = x_train.shape[1]
                x_train, x_test, y_train, y_test = train_test_split(x_train, y_train, test_size=0.2)
                print('x_train shape:', x_train.shape)
                print(x_train.shape[0], 'train samples')
                print(x_test.shape[0], 'test samples')
                # 將數字轉為 One-hot 向量
                print(type(x_train), type(y_train))
                y_train2 = tf.keras.utils.to_categorical(y_train, category)
                y_test2 = tf.keras.utils.to_categorical(y_test, category)
                print(x_train.shape)
                print(y_test2)

                datagen = tf.keras.preprocessing.image.ImageDataGenerator(
                    rotation_range=45,
                    width_shift_range=[-30, 30],
                    height_shift_range=[-30, 30],
                    data_format='channels_last')

                model = tf.keras.models.Sequential()
                conv_base.trainable = True
                # 加入 2D 的 Convolution Layer，接著一層 ReLU 的 Activation 函數
                model.add(conv_base)
                for layers in conv_base.layers[:-12]:
                    layers.trainable = False
                model.add(tf.keras.layers.Dropout(rate=0.05))
                model.summary()
                # model.add(layers.GlobalAveragePooling2D())
                # model.add(layers.Dense(256,activation='relu'))
                # model.add(layers.Dense(256,activation='relu'))
                # 將 2D 影像轉為 1D 向量
                model.add(tf.keras.layers.Flatten())
                # 連接 Fully Connected Layer，接著一層 ReLU 的 Activation 函數
                model.add(tf.keras.layers.Dense(128, activation='relu'))
                # 連接 Fully Connected Layer，接著一層 Softmax 的 Activation 函數
                model.add(tf.keras.layers.Dense(256, activation='relu'))
                # model.add(tf.keras.layers.Dense(256, activation='relu'))
                # 連接 Fully Connected Layer，接著一層 Softmax 的 Activation 函數

                model.add(tf.keras.layers.Dense(units=category,
                                                activation=tf.nn.softmax))

                # 設定模型的 Loss 函數、Optimizer 以及用來判斷模型好壞的依據（metrics）
                model.compile(loss=tf.keras.losses.categorical_crossentropy,
                              optimizer=N(learning_rate=lr, weight_decay=0.00001),
                              metrics=['accuracy', tf.keras.metrics.Recall()])
                model.summary()
                # 可训练层
                for x in model.trainable_weights:
                    print(x.name)
                print('\n')

                # 不可训练层
                for x in model.non_trainable_weights:
                    print(x.name)
                print('\n')

                # with open("test.json", "w") as json_file:
                #     json_file.write(model.to_json())

                # checkpoint = tf.keras.callbacks.ModelCheckpoint("test.h5", monitor='loss', verbose=1,
                #     save_best_only=True, mode='auto', save_freq=1)

                # try:
                #     with open('test.h5', 'r') as save_weights:
                #         model.save_weights("test.h5")
                # except IOError:
                #     print("File not exists")
                #

                tensorboard = TensorBoard(log_dir="logs")
                traindata = datagen.flow(x_train, y_train2, batch_size=Bs)
                testdata = datagen.flow(x_test, y_test2, batch_size=Bs)
                # 訓練模型
                history = model.fit(traindata, validation_data=(testdata), validation_freq=1,
                                    epochs=epoch,
                                    batch_size=Bs,
                                    verbose=1)

                # # 保存模型架構
                # with open("test_zy.json", "w") as json_file:
                #     json_file.write(model.to_json())
                # # 保存模型權重
                # model.save_weights("test_zy.h5")
                # 測試
                score = model.evaluate(x_test, y_test2, batch_size=3)
                # 輸出結果
                print("score:", score)

                predict = model.predict(x_test)
                print(predict)
                print("Ans:", np.argmax(predict[0]), np.argmax(predict[1]), np.argmax(predict[2]), np.argmax(predict[3]))

                predict2 = model.predict(x_test)
                predict2 = np.argmax(predict2, axis=1)
                print("predict_classes:", predict2[:20])
                print("y_test", y_test[:20])

                predict3 = model.predict(x_train)
                predict3 = np.argmax(predict3, axis=1)

                end = time.perf_counter()
                print('Running time: %s Seconds' % (end - start))

                tf.compat.v1.disable_eager_execution()
                con_mat = tf.math.confusion_matrix(labels=y_test, predictions=predict2,
                                                   dtype=tf.int32, name=None)
                with tf.compat.v1.Session():
                    con_matValue = tf.Tensor.eval(con_mat, feed_dict=None, session=None)
                    print('Confusion Matrix: \n\n', con_matValue)

if __name__=="__main__":
    app=QApplication(sys.argv)
    window=mainwindow()
    window.setWindowTitle("刀具识别")
    sys.exit(app.exec_())
