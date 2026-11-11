class RizzlerCapture extends AudioWorkletProcessor {
  constructor(){super();this.buf=new Int16Array(1024);this.at=0}
  process(inputs){
    const x=inputs[0]?.[0];
    if(x)for(let i=0;i<x.length;i++){
      this.buf[this.at++]=Math.max(-32768,Math.min(32767,Math.round(x[i]*32767)));
      if(this.at===1024){const raw=this.buf;this.port.postMessage(raw,[raw.buffer]);this.buf=new Int16Array(1024);this.at=0}
    }
    return true;
  }
}
registerProcessor('rizzler-capture', RizzlerCapture);
