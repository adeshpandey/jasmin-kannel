# -*- coding: utf-8 -*-
import logging
import sys

import smpplib.gsm
import smpplib.client
import smpplib.consts

# if you want to know what's happening
logging.basicConfig(level='DEBUG')

system_id='adesh'
password='123456'
host='127.0.0.1'
port=2775
text=u'Test from Wasimaaa'
source_addr='unifonic'
destination_addr='966559470037'
registered_delivery=True

# Two parts, UCS2, SMS with UDH
parts, encoding_flag, msg_type_flag = smpplib.gsm.make_parts(text)

def call_smpp():
    client = smpplib.client.Client(host, port)
    client.connect()
    client.bind_transceiver(system_id=system_id, password=password)

    # Print when obtain message_id
    client.set_message_sent_handler(
        lambda pdu: sys.stdout.write('sent {} {}\n'.format(pdu.sequence, pdu.message_id)))
    client.set_message_received_handler(
        lambda pdu: sys.stdout.write('delivered {}\n'.format(pdu.receipted_message_id)))


    for part in parts:
        pdu = client.send_message(
            source_addr_ton=smpplib.consts.SMPP_TON_INTL,
            #source_addr_npi=smpplib.consts.SMPP_NPI_ISDN,
            # Make sure it is a byte string, not unicode:
            source_addr=source_addr,

            dest_addr_ton=smpplib.consts.SMPP_TON_INTL,
            #dest_addr_npi=smpplib.consts.SMPP_NPI_ISDN,
            # Make sure thease two params are byte strings, not unicode:
            destination_addr=destination_addr,
            short_message=part,

            data_coding=encoding_flag,
            esm_class=msg_type_flag,
            registered_delivery=registered_delivery,
        )
        print(part, pdu.sequence)
        
    # Enters a loop, waiting for incoming PDUs
    client.unbind()
    client.disconnect()

def set_msg():
    for i in range(10000):
        call_smpp()

import threading

thrds=[]
for i in range(100):
    t = threading.Thread(target=set_msg)
    t.start()
    thrds.append(t)

for t in thrds:
    t.join()

