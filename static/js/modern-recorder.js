// Modern Audio Recorder using AudioWorkletNode
class ModernRecorder {
    constructor(source, config = {}) {
        this.config = {
            bufferLen: 4096,
            numChannels: 1,
            mimeType: 'audio/wav',
            sampleRate: 16000,
            ...config
        };
        
        this.source = source;
        this.context = source.context;
        this.recording = false;
        this.audioData = [];
        this.workletNode = null;
        
        this.init();
    }
    
    async init() {
        try {
            // Register audio worklet processor
            await this.context.audioWorklet.addModule(this.createWorkletURL());
            
            // Create audio worklet node
            this.workletNode = new AudioWorkletNode(this.context, 'audio-recorder', {
                numberOfInputs: 1,
                numberOfOutputs: 1,
                channelCount: this.config.numChannels,
                channelCountMode: 'explicit',
                channelInterpretation: 'discrete'
            });
            
            // Handle messages from worklet
            this.workletNode.port.onmessage = (event) => {
                if (event.data.type === 'audioData') {
                    this.audioData.push(...event.data.data);
                }
            };
            
            // Connect source to worklet
            this.source.connect(this.workletNode);
            this.workletNode.connect(this.context.destination);
            
        } catch (error) {
            // AudioWorklet not supported, falling back to ScriptProcessor
            this.useModernAPI = false;
        }
        
        if (!this.useModernAPI) {
            // AudioWorklet not supported, using ScriptProcessor fallback
            this.initScriptProcessor();
        }
    }
    
    createWorkletURL() {
        const workletCode = `
            class AudioRecorderProcessor extends AudioWorkletProcessor {
                constructor() {
                    super();
                    this.buffer = [];
                }
                
                process(inputs, outputs, parameters) {
                    const input = inputs[0];
                    if (input && input.length > 0) {
                        // Send audio data to main thread
                        this.port.postMessage({
                            type: 'audioData',
                            data: Array.from(input[0])
                        });
                    }
                    return true;
                }
            }
            
            registerProcessor('audio-recorder', AudioRecorderProcessor);
        `;
        
        const blob = new Blob([workletCode], { type: 'application/javascript' });
        return URL.createObjectURL(blob);
    }
    
    record() {
        if (!this.workletNode) {
            throw new Error('Recorder not initialized');
        }
        
        this.recording = true;
        this.audioData = [];
    }
    
    stop() {
        if (!this.recording) {
            return;
        }
        
        this.recording = false;
    }
    
    exportWAV(callback, mimeType = 'audio/wav') {
        if (!this.audioData.length) {
            callback(new Blob([], { type: mimeType }));
            return;
        }
        
        // Convert audio data to WAV format
        const wavBlob = this.encodeWAV(this.audioData, this.config.sampleRate);
        callback(wavBlob);
    }
    
    encodeWAV(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        
        // WAV header
        this.writeString(view, 0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        this.writeString(view, 8, 'WAVE');
        this.writeString(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        this.writeString(view, 36, 'data');
        view.setUint32(40, samples.length * 2, true);
        
        // Write audio data
        this.floatTo16BitPCM(view, 44, samples);
        
        return new Blob([buffer], { type: 'audio/wav' });
    }
    
    writeString(view, offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }
    
    floatTo16BitPCM(output, offset, input) {
        for (let i = 0; i < input.length; i++, offset += 2) {
            const s = Math.max(-1, Math.min(1, input[i]));
            output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        }
    }
    
    clear() {
        this.audioData = [];
    }
    
    getBuffer() {
        return this.audioData;
    }
    
    destroy() {
        if (this.workletNode) {
            this.workletNode.disconnect();
            this.workletNode = null;
        }
        this.audioData = [];
    }
}

// Fallback to original recorder if AudioWorklet is not supported
class FallbackRecorder {
    constructor(source, config = {}) {
        this.config = {
            bufferLen: 4096,
            numChannels: 1,
            mimeType: 'audio/wav',
            ...config
        };
        
        this.source = source;
        this.context = source.context;
        this.recording = false;
        this.audioData = [];
        this.scriptNode = null;
        
        this.init();
    }
    
    init() {
        // Use deprecated ScriptProcessorNode as fallback
        this.scriptNode = this.context.createScriptProcessor(
            this.config.bufferLen,
            this.config.numChannels,
            this.config.numChannels
        );
        
        this.scriptNode.onaudioprocess = (e) => {
            if (!this.recording) return;
            
            const input = e.inputBuffer.getChannelData(0);
            this.audioData.push(...Array.from(input));
        };
        
        this.source.connect(this.scriptNode);
        this.scriptNode.connect(this.context.destination);
    }
    
    record() {
        this.recording = true;
        this.audioData = [];
    }
    
    stop() {
        this.recording = false;
    }
    
    exportWAV(callback, mimeType = 'audio/wav') {
        if (!this.audioData.length) {
            callback(new Blob([], { type: mimeType }));
            return;
        }
        
        const wavBlob = this.encodeWAV(this.audioData, this.context.sampleRate);
        callback(wavBlob);
    }
    
    encodeWAV(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        
        // WAV header
        this.writeString(view, 0, 'RIFF');
        view.setUint32(4, 36 + samples.length * 2, true);
        this.writeString(view, 8, 'WAVE');
        this.writeString(view, 12, 'fmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        this.writeString(view, 36, 'data');
        view.setUint32(40, samples.length * 2, true);
        
        // Write audio data
        this.floatTo16BitPCM(view, 44, samples);
        
        return new Blob([buffer], { type: 'audio/wav' });
    }
    
    writeString(view, offset, string) {
        for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
        }
    }
    
    floatTo16BitPCM(output, offset, input) {
        for (let i = 0; i < input.length; i++, offset += 2) {
            const s = Math.max(-1, Math.min(1, input[i]));
            output.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
        }
    }
    
    clear() {
        this.audioData = [];
    }
    
    getBuffer() {
        return this.audioData;
    }
    
    destroy() {
        if (this.scriptNode) {
            this.scriptNode.disconnect();
            this.scriptNode = null;
        }
        this.audioData = [];
    }
}

// Factory function to create the appropriate recorder
function createRecorder(source, config = {}) {
    // Check if AudioWorklet is supported
    if (window.AudioWorklet && source.context.audioWorklet) {
        try {
            return new ModernRecorder(source, config);
        } catch (error) {
            // AudioWorklet not supported, falling back to ScriptProcessor
            return new FallbackRecorder(source, config);
        }
    } else {
        // AudioWorklet not supported, using ScriptProcessor fallback
        return new FallbackRecorder(source, config);
    }
}

// Export for use in other files
window.createRecorder = createRecorder; 