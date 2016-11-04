import os
import wpf
from mvvm import ViewModel, Notifiable, command, notifiable, List
from System.Windows import Application, Window
from fractions import Fraction
from decimal import Decimal


frac = lambda a : Fraction(Decimal(a))

class MyViewModel(ViewModel):
    outputText = Notifiable('')
    inputText = Notifiable('')
    outputNumber = Fraction(0)
    prevOperator = '='


    operators = {'+':lambda a, b : a + frac(b),\
                 '-':lambda a, b : a - frac(b),\
                 'x':lambda a, b : a * frac(b),\
                 '/':lambda a, b : a / frac(b),\
                 '=':lambda a, b : frac(b) }

    @command
    def addDigitCommand(self, param):
        tempText = self.inputText + param
        try:
            float(tempText) # 数値か検査
            self.inputText = tempText # 数値だったら入力ok
        except ValueError:
            pass # 数値じゃなかったら無視
    
    @command    
    def operatorCommand(self, param):
        if 'AC' == param:
            self.outputText = ''
            self.outputNumber = Fraction(0)
            self.prevOperator = '='
        if 'C' in param:
            self.inputText = ''
            return
        if self.inputText is '':
            self.prevOperator = param
            return
        if self.outputText is '':
            self.outputText = 0
        if self.prevOperator == '/' and float(self.inputText) == 0:
            self.inputText = ''
            self.outputText = ''
            return
           
        self.outputNumber = self.operators[self.prevOperator](self.outputNumber, self.inputText)
        self.prevOperator = param
        self.inputText = ''
        self.outputText = str(float(self.outputNumber))

class MyWindow(Window):
    def __init__(self):
        wpf.LoadComponent(self, os.path.join(os.path.dirname(__file__), 'Clac_Ironpython.xaml'))
        self.DataContext = MyViewModel()

if __name__ == '__main__':
    Application().Run(MyWindow())
