#!/bin/env python3

from socket import *
import threading
from datetime import datetime
from enum import *
import os, sys, traceback, selectors

class messageStatus(Enum):
        UNKNOWN_MSG = -1
        REQ_CONN = 0
        REQ_DISCONN = 1
        PLAIN_MSG = 2
        REQ_MSG = 3

class client:
#Store information about clients
    def __init__(self, clientSocket : socket, address : str, uid : int, sid : int):
        """
        Data container for client information

        Arguments:
        clientSocket : socket - general-purpose socket for all client communications
        address : str - client's IP address
        uid : int - client's uid marking his position in the server's client dict
        sid : int - client's unique session ID
        """
        self.clientSocket = clientSocket
        self.address = address
        #uid is stored for convenience
        self.uid = uid
        #sid is session id, unique for every session
        self.sid = sid
        self.ping : int = 0
        self.log = log()
        self.CLIENTTIME = 0
        self.clientStatus = False
        self.messageBuffer : list = []

class message:
#for monitoring client communications; stores the message itself and its sender
    def __init__(self, sid : int, message : str):
        self.sender = sid
        self.text = message
        self.recipients : list = []

class log:
#logs messages

    def __init__(self, logfile : str = 'log'):
        self.messages : dict = {}
        self.output = []
        #s - server, clc - client connection, clms - server operations on client messages, clm - plain client messages
        self.loggedTypes = ['s', 'clc', 'clms', 'clm']
        self.startTime = datetime.now().strftime('%d-%m-%y %H:%M:%S.log')
        self.logfile = logfile + self.startTime

    def dump(self):
        messages = self.messages.values()
        with open(self.logfile, 'a') as logfile:
            for msg in messages:
                msg += '\n'
                logfile.write(msg)
            logfile.close()
        self.messages.clear()

    def get_prefix(self, mtype : str):
        prefix = 'UNKNOWN'
        if mtype == 's':
            prefix = 'SERVER: '
        elif mtype == 'clc':
            prefix = 'CLIENT CONNECTION: '
        elif mtype == 'clms':
            prefix = 'CLIENT MESSAGE INTERNAL: '
        elif mtype == 'clm':
            prefix = 'CLIENT MESSAGE: '
        return prefix

    def log_message(self, msg : str, mtype: str):
        loctime = datetime.now()
        stime = loctime.strftime('%d-%m-%y %H:%M:%S ')
        prefix = self.get_prefix(mtype)
        msg = stime + prefix + msg
        self.messages[loctime] = msg
        if mtype in self.loggedTypes:
            self.output.append(msg)

    def collect_messages(self):
        collectedMessages = []
        for msg in self.output:
            collectedMessages.append(msg)
        self.output.clear()
        return collectedMessages

    def update(self):
        if self.messages:
            self.dump()


class server:
#Process all client-server interactions
    def __init__(self):
        self.PORT : int
        self.SERVER_IP : str
        self.socket : socket
        self.serverPassword = 'abc'
        self.msgQueue : list = []
        self.clients : dict = {}
        self.freeIds : list = []
        self.sessionCount = 0
        self.Working : bool = False
        self.maxQueue = 20
        self.log = log()
        self.serverSelector = selectors.DefaultSelector()
        self.SERVERTIME : int = 0

    def _get_client_by_addr(self, addr : str):
        """
        Find the client by his IP address -> client : client, client.uid : int

        Arguments:
        addr : str - client's IP address
        """
        for uid in self.clients:
            if self.clients[uid].addr == addr:
                self.clients[uid] = client
                return client, client.uid

    def _clear_buffer(self, uid : int):
        """
        Dump client's message buffer to the message queue

        Arguments:
        uid : int - client's id
        """
        messagingClient = self._get_client_by_id(uid)
        sid = messagingClient.sid
        if messagingClient.messageBuffer:
            for msg in messagingClient.messageBuffer:
                msg = message(sid, msg)
                self.msgQueue.append(msg)
                if len(self.msgQueue) > self.maxQueue:
                    del self.msgQueue[0]
            messagingClient.messageBuffer.clear()

    def _get_client_by_socket(self, clientSocket : socket):
        """
        Find the client by his socket -> client : client, client.uid : int

        Arguments:
        clientSocket : socket - client's socket
        """
        for uid in self.clients:
            client = self.clients[uid]
            if client.clientSocket == clientSocket:
                return client, client.uid

    def _get_client_by_id(self, uid : int):
        """
        Find the client by his uid -> client : client

        Arguments:
        uid : int - client's uid
        """
        return self.clients[uid]

    def disconnect(self, uid):
        """
        Disconnect the client by his uid, cease servicing him

        Arguments:
        uid : int -- client id
        """
        self.log.log_message('Disconnecting client %d...' % uid, 'clc')
        client = self.clients[uid]
        self.log.log_message('Unregistering selector %d...' % uid, 's')
        self.serverSelector.unregister(client.clientSocket)
        self.log.log_message('Closing socket %d...' % uid, 's')
        client.clientSocket.close()
        self.log.log_message('Deleting client %d...' % uid, 's')
        del self.clients[uid]
        self.freeIds.append(uid)
        self.log.log_message('Client %d disconnected.' % uid, 'clc')

    def _get_message(self, uid : int):
        """
        Get a message from the client

        Arguments:
        uid : int -- client id
        """
        messagingClient = self._get_client_by_id(uid)
        sid = messagingClient.sid
        clientSocket = messagingClient.clientSocket
        msg = clientSocket.recv(512)
        if msg:
            msg = msg.decode()
            code, msg = self._process_message(msg)
            if code == messageStatus.PLAIN_MSG:
                messagingClient.messageBuffer.append(msg)
                self.log.log_message ('%d SENT: %s' %(uid, msg), 'clms')
                self.log.log_message ('%d: %s' % (uid, msg), 'clm')
            elif code == messageStatus.REQ_DISCONN:
                self.log.log_message('%d REQUESTED DISCONNECT' % uid, 'clc')
                self.send_message(uid, 'dc req', True, -1)
                self.disconnect(uid)
            elif code == messageStatus.REQ_MSG:
                self.log.log_message('%d REQUESTED MESSAGES' % uid, 'clms')
                for msg in self.msgQueue:
                    msgText = msg.text
                    sender = msg.sender
                    msgText = 'pm ' + msgText
                    if sender != sid and sid not in msg.recipients:
                        self.send_message(uid, msgText, sender=sender)
                    msg.recipients.append(sid)

            else:
                self.log.log_message('%d SENT some GIBBERISH: %s' % (uid, msg), 'clms')
        else:
            self.log.log_message('CONN LOST with %d' % uid, 'clc')
            self.disconnect(uid)

    def send_message(self, uid : int, msg : str, sysmes: bool = False, sender : int = -1):
        """
        Sends a message to the particular client

        Arguments:
        uid : int -- recipient's uid
        msg : str -- message to be sent
        sysmes : bool -- denotes whether the message is meant for the system
        sender : int -- sender's id
        """
        if not sysmes:
            msg = '%d: %s' % (sender, msg)
        encodedMsg = msg.encode()
        messagingClient = self._get_client_by_id(uid)
        clientSocket = messagingClient.clientSocket
        clientSocket.sendall(encodedMsg)
        self.log.log_message('%d SENT TO %d: %s' % (sender, uid, msg), 'clms')

    def _get_new_id(self):
        """
        Return a free ID, or generates a new one if none exist. -> newId : int
        """
        newId = len(self.clients)
        if self.freeIds:
            newId = self.freeIds.pop(0)
        sid = self.sessionCount
        self.sessionCount += 1
        return newId, sid

    def _handshake(self, uid : int):
        """
        Confirms client connection, connects them if confirmed

        Arguments:
        uid : int - client's id
        """
        shakenSocket = self.clients[uid].clientSocket
        handmsg = 'sc -1'
        msg = shakenSocket.recv(512).decode()
        if msg:
            code, msg = self._process_message(msg)
            self.log.log_message('Performing handshake with %d...' % uid, 'clc')
            if code == messageStatus.REQ_CONN and msg == self.serverPassword:
                self.log.log_message('%d CONFIRMED' % uid, 'clc')
                handmsg = 'sc 0'
            elif msg != self.serverPassword:
                self.log.log_message('%d WRONG PASSWORD %s' % (uid, msg), 'clc')
                handmsg = 'sc 1'

            self.send_message(uid, handmsg, True, -1)
            if handmsg == 'sc 0':
    #            self.ping(client)
                client = self._get_client_by_id(uid)
                client.clientStatus = True
                pass
        else:
            self.disconnect(uid)

    def _process_message(self, msg : str):
        """
        Process a string, reading its header, returning its type and body -> messageType : userSent, body : str

        Arguments:
        msg : str - message to process
        """
        msg = msg.split()
        head = msg[0]
        try:
            body = ' '.join(msg[1::])
        except IndexError:
            body = ''
        messageType : userSent
        if head == 'rc':
            messageType = messageStatus.REQ_CONN
        elif head == 'rd':
            messageType = messageStatus.REQ_DISCONN
        elif head == 'pm':
            messageType = messageStatus.PLAIN_MSG
        elif head == 'rm':
            messageType = messageStatus.REQ_MSG
        else:
            messageType = messageStatus.UNKNOWN_MSG
        return messageType, body

    def initialize(self):
        """
        Initialize the server, get the port and address, start up the socket
        """
        self.log.log_message('Initializing server...', 's')
        self.PORT = int(input('Input server port: '))
        self.SERVER_IP = '127.0.0.1'
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.socket.bind((self.SERVER_IP, self.PORT))
        self.log.log_message('Socket initialized at port %d...' % self.PORT, 's')
        self.socket.listen()
        self.Working = True
        self.log.log_message('Server working, starting selectors', 's')
        self.serverSelector.register(self.socket, selectors.EVENT_READ, data = -1)
        self.log.log_message('Selectors started. Server ready to go.', 's')

    def outLog(self):
        """
        Outputs the log to the console
        """
        logMsg = self.log.collect_messages()
        for message in logMsg:
            print(message)

    def _run(self):
        """
        Perform regular operations with the clients
        """
        if self.clients:
            for uid in self.clients:
                self._clear_buffer(uid)
        events = self.serverSelector.select(timeout = 1)
        for key, mask in events:
            uid = key.data
            if uid != -1:
                if self._get_client_by_id(uid).clientStatus == True:
                    self._get_message(uid)
                else:
                    self._handshake(uid)
            else:
                clientSocket, addr = self.socket.accept()
                clientSocket.setblocking(False)
                nid, sid = self._get_new_id()
                newClient = client(clientSocket, addr, uid, sid)
                self.clients[nid] = newClient
                self.log.log_message('%d connected from %s' % (nid, addr), 'clc')
                self.serverSelector.register(clientSocket, selectors.EVENT_READ, data=nid)

    def tick(self):
        """
        Run another server cycle
        """
        if self.Working:
            self.SERVERTIME += 1
            self.outLog()
            self._run()
            self.log.update()

    def shutdown(self):
        """
        Shut the server down, closing all connections and ceasing all server operations
        """
        self.log.log_message('Shutting down server...', 's')
        self.outLog()
        self.Working = False
        self.log.log_message('Closing all sockets...', 's')
        self.outLog()
        self.socket.close()
        if self.clients:
            clients = self.clients.copy()
            for uid in clients:
                self.disconnect(uid)
            clients.clear()
        self.log.log_message('Done. Server is shut down.', 's')
        self.outLog()
        self.log.dump()

mainServer = server()
mainServer.initialize()
try:
    while True:
        mainServer.tick()
except KeyboardInterrupt:
    print('Exitting...')
finally:
    print(traceback.format_exc())
    mainServer.shutdown()
