__author__    = 'Bojan Delic <bojan@delic.in.rs>'
__date__      = 'Aug 21, 2013'
__copyright__ = 'Copyright (c) 2013 Bojan Delic'


import weakref
from functools import partial
from Queue import Queue
from threading import Lock
from collections import defaultdict
import wpf

from System import TimeSpan
from System.Windows.Input import ICommand
from System import EventArgs
from System.Windows.Threading import DispatcherTimer
from System.ComponentModel import INotifyPropertyChanged, PropertyChangedEventArgs
from System.Collections.ObjectModel import ObservableCollection


class MvvmError(Exception):
    pass


class WeakCallable(object):
    '''
    Weak reference to bound methods.

    Because bound method is created at the moment when it is accessed every
    time, it will be garbage collected very soon, even if object it is bound
    to is not garbage collected. This class holds weak references to
    methods `im_self` and `im_func` that will not be garbage collected
    until `self` of the method is alive.
    '''

    def __init__(self, func, on_collect=None):
        '''
        Both `on_func_collect` and `on_self_collect` should accept single
        parameter that will be instance of :class:`.WeakCallable` that died.

        :param callable func:
            Methods to create weak reference for.
        :param callable on_collect:
            Callable that will be called when function is garbage collected.
        '''
        self._ext_on_collect = on_collect
        if hasattr(func, 'im_func'):  # if this is method
            self._func = weakref.ref(func.im_func)
            self._obj = weakref.ref(func.im_self, self._on_collect)
        else:
            self._func = weakref.ref(func, self._on_collect)
            self._obj = None

    def __call__(self, *args, **kwargs):
        if self._obj is not None:
            cl = self._func()
            obj = self._obj()
            if cl is not None and obj is not None:
                return cl(obj, *args, **kwargs)
            else:
                raise weakref.ReferenceError('Object no longer available')
        else:
            cl = self._func()
            if cl is not None:
                return cl(*args, **kwargs)
            else:
                raise weakref.ReferenceError('Function no longer available')

    def _on_collect(self, ref):
        if self._ext_on_collect is not None:
            self._ext_on_collect(self)


class _Messenger(object):
    '''
    Thread-safe messenger that ensures that all message handlers are executed
    in main dispatcher thread.

    This class should be used as singleton. It is not enforced, but recomanded
    way of getting instance is by using :meth:`_Messenger.instance` class
    method.
    '''

    _instance = None

    @classmethod
    def instance(cls, interval=5):
        '''
        Returns existing instance of messenger. If one does not exist it will
        be created and returned.

        :param int interval:
            Number of miliseconds that represents interval when messages will
            be processed.
            Note that this parameter will be used only the first time when
            instance is requested, every other time it will be ignored
            because existing instance of :class:`._Messenger` is returned.
        '''
        if not cls._instance:
            cls._instance = _Messenger(interval)
        return cls._instance

    def __init__(self, interval=5):
        '''
        :param int interval:
            Number of milliseconds that represents interval when messages will
            be processed.
        '''
        self._subscribers = defaultdict(list)
        self._messages = Queue()
        self._lock = Lock()
        self._timer = DispatcherTimer()
        self._timer.Interval = TimeSpan.FromMilliseconds(5)
        self._timer.Tick += self._execute
        self._timer.Start()

    def send(self, message, *args, **kwargs):
        '''
        Sends provided message to all listeners. Message is only added to
        queue and will be processed on next tick.

        :param Message message:
            Message to send.
        '''
        self._messages.put((message, args, kwargs), False)

    def subscribe(self, message, handler):
        '''
        Adds hander for specified message.

        :param str message:
            Name of message to subscribe to.

        :param callable handler:
            Handler for this message type. Handler must receive single parameter
            and that parameter will be instance of sent message.
        '''
        with self._lock:
            ref = WeakCallable(handler, self._on_collect)
            self._subscribers[message].append(ref)

    # TODO: Unsubscribing with WeakCallable does not work
    def unsubscribe(self, message, handler):
        '''
        Removes handler from message listeners.

        :param str message:
            Name of message to unsubscribe handler from.

        :param callable handler:
            Callable that should be removed as handler for `message`.
        '''
        with self._lock:
            self._subscribers[message].remove(WeakCallable(handler))

    def _execute(self, sender, event_args):
        '''
        Event handler for timer that processes all queued messages.
        '''
        with self._lock:
            while not self._messages.empty():
                msg, args, kwargs = self._messages.get(False)
                for subscriber in self._subscribers[msg]:
                    try:
                        subscriber(*args, **kwargs)
                    except weakref.ReferenceError:
                        # Reference to handler is lost and it is OK to silence it
                        pass

    def _on_collect(self, ref):
        with self._lock:
            for msg in self._subscribers:
                if ref in self._subscribers[msg]:
                    self._subscribers[msg].remove(ref)


class Signal(object):
    '''Signal object for messaging.

    Can be used to connect directly to an object without specifying
    the message name. It works similarly to Qt Signals and Slots.
    '''
    def __init__(self, name=None):
        '''
        :param str name:
            Name of signal, for easier debuging. If not provided name of
            property to which signal is assigned to will be used if signal
            is creates in :class:`.ViewModel` class.
        '''
        self._messanger = _Messenger.instance()

    def connect(self, handler):
        '''
        Connects handler to this signal.
        '''
        self._messanger.subscribe(self, handler)

    def disconnect(self, handler):
        '''
        Disconnects handler from this singal.
        '''
        self._messanger.unsubscribe(self, handler)

    def emit(self, *args, **kwargs):
        '''
        Emits this signal. As result, all handlers will be invoked.
        '''
        self._messanger.send(self, *args, **kwargs)

    def __str__(self):
        return 'signal {name}'.format(name=self.name)


class notifiable(property):
    '''
    Decorator that replaces @property decorator by adding raising
    property changed event when setter is invoked.

    Example of usage::

        class MyViewModel(ViewModel):
            @notifiable
            def foo(self):
                return self._foo
            @foo.setter
            def foo(self, value):
                self._foo = value

    For simple properties without getter and setter function and with
    automatic event raising :class:`.Notifiable` can be used.

    Idea and initial code for this is taken from
    http://gui-at.blogspot.com/2009/11/inotifypropertychanged-in-ironpython.html
    '''
    def __init__(self, getter):
        def newgetter(slf):
            try:
                return getter(slf)
            except AttributeError:
                return None
        super(notifiable, self).__init__(newgetter)

    def setter(self, setter):
        def newsetter(slf, newvalue):
            oldvalue = self.fget(slf)
            if oldvalue != newvalue:
                setter(slf, newvalue)
                slf.RaisePropertyChanged(setter.__name__)
        return property(fget=self.fget,
                        fset=newsetter,
                        fdel=self.fdel,
                        doc=self.__doc__)


_OCO = ObservableCollection[object]


class List(_OCO):
    '''
    ObservableCollection that can be used as ordinary python :class:`list`.
    '''
    append = _OCO.Add
    count = _OCO.Count
    index = _OCO.IndexOf
    insert = _OCO.Insert
    remove = _OCO.Remove

    def extend(self, seq):
        for item in seq:
            return self.Add(item)

    def pop(self, index=None):
        if index:
            return self.RemoveAt(index)
        else:
            return self.RemoveAt(self.Count - 1)

    def __getitem__(self, y):
        return list(self)[y]


class Notifiable(object):
    '''
    Descriptor class that raises `PropertyChanged` event when new value is
    set. For this to work, this descriptor can only be used in classes that
    implements interface `INotifyPropertyChanged`

    Class is designed to work with subclasses of :class:`ViewModel`
    because this class implements `INotofyPropertyChanged` and adds metaclass
    that discovers names of variables for raising events.

    Example of usage::

        class MyViewModel(ViewModel):
            my_property = NotifProperty()
    '''
    def __init__(self, initial=None, name=None):
        '''
        :param initial:
            Initial value of this property.

        :param name:
            Name of this property. If not provided and if this is used with
            :class:`.ViewModel`, name will be set automatically to name
            of property.
        '''
        self.name = name
        self.initial = initial

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        return getattr(obj, '__notifiable_%s' % self.name, self.initial)

    def __set__(self, obj, value):
        current = getattr(obj, '__notifiable_%s' % self.name, self.initial)
        if current != value:
            setattr(obj, '__notifiable_%s' % self.name, value)
            obj.RaisePropertyChanged(self.name)

    def __delete__(self, obj):
        if hasattr(obj, '__notifiable_%s' % self.name):
            delattr(obj, '__notifiable_%s' % self.name)


class ViewModelMeta(type):
    '''
    MetaClass that examines fields of new class and populates names of
    :class:`.NotifProperty` fields to names of variables.
    '''
    def __new__(cls, name, bases, dct):
        super_new = super(ViewModelMeta, cls).__new__
        for name, val in dct.items():
            if isinstance(val, (Notifiable, Signal)):
                if not hasattr(val, 'name') or not val.name:
                    val.name = name
        return super_new(cls, name, bases, dct)


class ViewModel(object, INotifyPropertyChanged):
    '''
    Base ViewModel class that all view-model classes should inherit from.
    '''
    __metaclass__ = ViewModelMeta

    def __init__(self):
        self.property_chaged_handlers = []
        self.messenger = _Messenger.instance()

    def RaisePropertyChanged(self, property_name):
        '''
        Raises event that property value has changed for provided property name.

        :param str property_name:
            Name of property whose value has changed.
        '''
        args = PropertyChangedEventArgs(property_name)
        for handler in self.property_chaged_handlers:
            handler(self, args)

    def add_PropertyChanged(self, handler):
        self.property_chaged_handlers.append(handler)

    def remove_PropertyChanged(self, handler):
        self.property_chaged_handlers.Remove(handler)


class Command(ICommand):
    '''
    Implementation of WPF command.
    '''
    def __init__(self, execute, can_execute=None):
        self.execute = execute
        self.can_execute = can_execute
        self._can_execute_changed_handlers = []

    def Execute(self, parameter):
        '''
        Executes handler for this command.
        '''
        self.execute(parameter)

    def add_CanExecuteChanged(self, handler):
        '''
        Adds new listener to CanExecuteChanged event.
        '''
        self._can_execute_changed_handlers.append(handler)

    def remove_CanExecuteChanged(self, handler):
        '''
        Removes listener for CanExecuteChanged event.
        '''
        self._can_execute_changed_handlers.remove(handler)

    def RaiseCanExecuteChanged(self):
        '''
        Raises CanExecuteChanged event.
        '''
        for handler in self._can_execute_changed_handlers:
            handler(self, EventArgs.Empty)

    def CanExecute(self, parameter):
        '''
        Returns `True` if command can be executed, `False` otherwise.
        '''
        if self.can_execute:
            return self.can_execute()
        return True


class command(object):
    '''
    Decorator to that turns method to command handler. Example of usage::

        class MyClass(ViewModel):
            @command
            def command_handler(self):
                # do something
                pass
            @command_handler.can_execute
            def command_can_execute(self):
                # return True if command can execute, False otherwise
                return True
    '''
    def __init__(self, handler, can_execute=None):
        '''
        :param callable handler:
            Method that will be called when command executed.

        :param callable can_execute:
            Method that will be called when GUI needs information if command
            can be executed. If not provided, default implementation always
            returns `True`.
        '''
        self._handler = handler
        self._can_execute = can_execute
        self._command = None

    def __get__(self, obj, objtype):
        if not self._handler:
            raise AttributeError('Unable to get field')
        if not self._command:
            self._command = Command(partial(self._handler, obj),
                                    partial(self._can_execute, obj) if self._can_execute else None)
        return self._command

    def can_execute(self, can_execute):
        '''
        Decorator that adds function that determines if command can be executed.

        Decorated function should return `True` if command can be executed
        and false if it can not.
        '''
        self._can_execute = can_execute
