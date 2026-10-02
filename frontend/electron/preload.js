const { contextBridge } = require('electron');
contextBridge.exposeInMainWorld('vibepcb', { version: '0.1.0' });
