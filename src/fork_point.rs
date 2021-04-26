use std::sync::mpsc::{Receiver, Sender, TryRecvError};
use std::thread::JoinHandle;

use crate::core::Oid;
use git_wrapper::is_ancestor;
use std::sync::mpsc;
use std::thread;

pub struct ForkPointThread {
    thread: JoinHandle<()>,
    receiver: Receiver<ForkPointResponse>,
    sender: Sender<ForkPointRequest>,
}

pub struct ForkPointRequest {
    pub first: Oid,
    pub second: Oid,
    pub working_dir: String,
}

pub struct ForkPointResponse {
    pub oid: Oid,
    pub value: bool,
}

impl ForkPointThread {
    pub(crate) fn new() -> Self {
        let (tx_1, rx_1): (Sender<ForkPointResponse>, Receiver<ForkPointResponse>) =
            mpsc::channel();
        let (tx_2, rx_2): (Sender<ForkPointRequest>, Receiver<ForkPointRequest>) = mpsc::channel();
        let child = thread::spawn(move || {
            while let Ok(v) = rx_2.recv() {
                let t = is_ancestor(
                    v.working_dir.as_str(),
                    &v.first.to_string(),
                    &v.second.to_string(),
                )
                .expect("Execute merge-base --is-ancestor");
                tx_1.send(ForkPointResponse {
                    oid: v.first,
                    value: t,
                })
                .unwrap();
            }
        });
        ForkPointThread {
            thread: child,
            receiver: rx_1,
            sender: tx_2,
        }
    }

    pub(crate) fn send(&self, req: ForkPointRequest) {
        self.sender.send(req);
    }

    pub(crate) fn try_recv(&self) -> Result<ForkPointResponse, TryRecvError> {
        self.receiver.try_recv()
    }
}