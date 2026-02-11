declare module 'prism-media' {
  import { Transform } from 'stream';

  namespace opus {
    interface DecoderOptions {
      rate: number;
      channels: number;
      frameSize: number;
    }

    interface EncoderOptions {
      rate: number;
      channels: number;
      frameSize: number;
    }

    class Decoder extends Transform {
      constructor(options: DecoderOptions);
      decode(data: Buffer): Buffer | null;
    }

    class Encoder extends Transform {
      constructor(options: EncoderOptions);
      encode(data: Buffer): Buffer | null;
    }
  }

  namespace FFmpeg {
    interface FFmpegOptions {
      args?: string[];
    }

    class FFmpeg extends Transform {
      constructor(options?: FFmpegOptions);
    }
  }

  export { opus, FFmpeg };
}
