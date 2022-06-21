#!/bin/env python3
from socket import *
import selectors, threading

PORT = int(input('Enter the port: '))
ADDR = '127.0.0.1'
CONNECTED = False
cliSock = socket()
cliSock.bind((ADDR, PORT))
socketSelector = selectors.DefaultSelector()
messageBuffer = []
updateCounter = 0
slipping = False

def disconnect():
    global CONNECTED
    cliSock.close()
    CONNECTED = False

def request_connect(pWord : str = ''):
    request = 'rc ' + pWord
    cliSock.sendall(request.encode())
    print('Connection requested...')

def read_input():
    while CONNECTED:
        global slipping
        msg = input("Send a message: ")
        slipping = False
        msg = msg + '\n'
        if msg[0] != '/':
            msg = 'pm ' + msg
        else:
            msg = msg[1:]
        messageBuffer.append(msg.encode())

def connect():
    global CONNECTED
    servAddr = input('Server address: ')
    servPort = int(input('Server port: '))
    cliSock.connect((servAddr, servPort))
    pWord = input('Password: ')
    request_connect(pWord)
    response = cliSock.recv(512).decode().split()
    print(response)
    while True:
        if response[0] != 'sc' or len(response) < 2:
            print('Bad response. Terminating connection...')
            disconnect()
            break
        else:
            rcode = response[1]
            print('Received response...')
            if rcode == '0':
                print('Confirmed connection.')
                CONNECTED = True
                cliSock.setblocking(False)
                socketSelector.register(cliSock, selectors.EVENT_READ)
                inputThread = threading.Thread(target = read_input)
                inputThread.start()
                break
            elif rcode == '1':
                print('Wrong password. Try again...')
                pWord = input('Password: ')
                request_connect(pWord)
                response = cliSock.recv(512).decode().split()
            elif rcode == '-1':
                print('Unknown error.')
                break

def tick():
    global CONNECTED
    global updateCounter
    global slipping
    while True:
        if CONNECTED:
            updateCounter += 1
            events = socketSelector.select(timeout = 1)
            if messageBuffer:
                msg = messageBuffer.pop(0)
                cliSock.sendall(msg)
            for key, mask in events:
                sock = key.fileobj
                msg = sock.recv(512).decode()
                if msg:
                    if slipping == False:
                        msg = '\n'+msg
                        slipping = True
                    print(msg)
                else:
                    print('DISCONNECTED')
                    CONNECTED = False
                    cliSock.close()
            if updateCounter > 5:
                messageBuffer.append('rm'.encode())
                updateCounter = 0

connect()
while CONNECTED:
    try:
        tick()
    except KeyboardInterrupt:
        disconnect()
